"""Frame cost ceilings and reference-only multiworker variation, before a new GPU job."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba
from xpu2.material_job_metrics import compare,envelope,qualified,cpu_totals
from xpu2_cpu_cost_probe import renderer_pids
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('build','reference','fixtures','output'):
        p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--threads',type=int,choices=(1,12),required=True)
    p.add_argument('--resume',type=Path)
    p.add_argument('--names',default='diffuse,layered,textured,many_adaptive')
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(status='incomplete',threads=a.threads,bridge_enabled=False,runs=[],envelopes={})
    def save():
        temporary=out/'report.pending.json'
        temporary.write_text(json.dumps(report,indent=2)+'\n')
        os.replace(temporary,out/'report.json')
    try:
        gates=ROOT/'xpu2/MATERIAL_JOB_GATES.json'
        report['protocol']=dict(path=str(gates),sha256=digest_file(gates))
        (out/'protocol.json').write_bytes(gates.read_bytes())
        build=a.build.resolve();rt=build/'runtime';ref=a.reference.resolve()
        b=json.loads((build/'report.json').read_text())
        if b['status']!='built' or digest_file(rt/'librendering_rndr.dll')!=b['dll_sha256']:
            raise ValueError('Invalid CPU scope build')
        pinned={**b['source_hashes'],**b['native_hashes']}
        for f in (Path(__file__),ROOT/'xpu2/material_job_metrics.py',ROOT/'tools/xpu2_cpu_cost_probe.py',gates):
            pinned[str(f.resolve())]=digest_file(f)
        for module in tuple(sys.modules.values()):
            filename=getattr(module,'__file__',None)
            if filename:
                source=Path(filename).resolve()
                if source.is_relative_to(ROOT) and source.suffix=='.py':
                    pinned[str(source)]=digest_file(source)
        for f,h in pinned.items():
            if digest_file(Path(f))!=h:
                raise ValueError('Source drift '+f)
        report['source_hashes']=pinned
        prior=None
        if a.resume:
            prior=json.loads(a.resume.read_text())
            if prior['threads']!=a.threads or prior['bridge_enabled'] is not False or prior['protocol']['sha256']!=digest_file(gates):
                raise ValueError('Resume configuration mismatch')
            for f,h in prior['source_hashes'].items():
                checked=a.resume.parent/'probe_at_capture.py' if Path(f).resolve()==Path(__file__).resolve() else Path(f)
                if digest_file(checked)!=h:
                    raise ValueError('Resume source drift '+str(checked))
            for row in prior['runs']:
                if not row['execution']['passed'] or digest_file(Path(row['artifact_folder'])/'beauty.exr')!=row['image_sha256']:
                    raise ValueError('Resume artifact changed')
            report['runs']=prior['runs']
            report['resumed_from']=dict(path=str(a.resume.resolve()),sha256=digest_file(a.resume),reason=prior.get('error'))
        held={str(r):inventory(r) for r in (rt,ref)}
        report['runtime_inventories']=held;report['gpu']=gpu_identity()
        report['logical_cpus']=os.cpu_count()
        scenes={name:a.fixtures.resolve()/(name+'.rdla') for name in a.names.split(',')}
        assets={str(f):digest_file(f) for f in (*scenes.values(),*a.fixtures.resolve().glob('pattern.*'))}
        report['asset_hashes']=assets
        if prior and (prior['asset_hashes']!=assets or prior['runtime_inventories']!=held or prior['gpu']!=report['gpu']):
            raise ValueError('Resume assets/runtime/GPU changed')
        save()
        n=1 if a.threads==1 else 5
        for name,scene in scenes.items():
            references=[];bound=None
            cases=[('reference'+str(i),0,0,True) for i in range(n)]
            cases += [('off_before',0,0,False),('sample64',64,173,False),('sample16',16,761,False),('off_after',0,0,False)]
            for label,rate,seed,is_ref in cases:
                existing=next((r for r in report['runs'] if r['fixture']==name and r['label']==label),None)
                if existing:
                    if is_ref:
                        folder=Path(existing['artifact_folder'])
                        references.append(read_rgba(ref,folder/'beauty.exr',out,'resume-'+name+'-'+label,environment(ref,out)))
                        if len(references)==5:
                            bound=envelope(references);report['envelopes'][name]=bound
                    continue
                folder=out/(name+'-'+label);folder.mkdir();runtime=ref if is_ref else rt
                env=environment(runtime,folder)
                if rate:
                    env.update(XPU2_CPU_COST=str(folder/'cpu.csv'),XPU2_CPU_COST_RATE=str(rate),XPU2_CPU_COST_SEED=str(seed))
                if renderer_pids():
                    raise ValueError('Competing renderer active; no timing started')
                print(name,a.threads,label,flush=True)
                start=time.perf_counter();competition=set()
                with (folder/'render.log').open('w') as log:
                    proc=subprocess.Popen([str(runtime/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads',str(a.threads),'-info','-stats',str(folder/'stats.csv')],env=env,cwd=folder,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                    deadline=time.monotonic()+600
                    try:
                        while proc.poll() is None:
                            competition.update(pid for pid in renderer_pids() if pid!=proc.pid)
                            if time.monotonic()>deadline:
                                raise TimeoutError('Render exceeded 600 seconds')
                            try:
                                proc.wait(timeout=.25)
                            except subprocess.TimeoutExpired:
                                pass
                    finally:
                        if proc.poll() is None:
                            proc.kill();proc.wait(timeout=10)
                wall=time.perf_counter()-start
                if competition or renderer_pids():
                    raise ValueError('Competing renderer contaminated timing '+str(sorted(competition)))
                log=(folder/'render.log').read_text(errors='replace')
                stats=(folder/'stats.csv').read_text(errors='replace') if (folder/'stats.csv').exists() else ''
                execution=successful('xpu',a.threads,proc.returncode,log,stats,(folder/'beauty.exr').exists())
                row=dict(fixture=name,label=label,rate=rate,seed=seed,artifact_folder=str(folder),process_wall_seconds=wall,execution=execution)
                report['runs'].append(row);save()
                if not execution['passed']:
                    raise ValueError('Native execution failed '+name+' '+label)
                errors=[line for line in log.splitlines() if any(s in line.lower() for s in ('rdla error','could not open','unable to open','unknown attribute','not a valid attribute'))]
                if errors:
                    raise ValueError(str(errors[:5]))
                rgba=read_rgba(runtime,folder/'beauty.exr',folder,'raw',env)
                row['image_sha256']=rgba['sha256']
                # Even reference zero-images/NaNs must not pass without checking all values.
                compare(rgba,rgba)
                if is_ref:
                    references.append(rgba)
                    if len(references)==5:
                        bound=envelope(references);report['envelopes'][name]=bound
                        # Freeze reference variation before any candidate render.
                        (out/(name+'-envelope.json')).write_text(json.dumps(bound,indent=2)+'\n')
                else:
                    row['comparisons']=[compare(r,rgba) for r in references]
                    row['image_qualified']=qualified(row['comparisons'],bound)
                    if rate:
                        row['cpu']=cpu_totals(folder/'cpu.csv')
                    save()
                    if not row['image_qualified']:
                        print('IMAGE GATE FAILED; retained as diagnostic only:',name,label,flush=True)
                save()
        for f,h in {**assets,**pinned}.items():
            if digest_file(Path(f))!=h:
                raise ValueError('Input changed during measurement '+f)
        for r in (rt,ref):
            verify(r,held[str(r)])
        report['status']='failed' if any(r.get('image_qualified') is False for r in report['runs']) else 'passed'
    except Exception as e:
        import traceback
        report.update(error=str(e),traceback=traceback.format_exc())
    save();print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1

if __name__=='__main__':
    raise SystemExit(main())
