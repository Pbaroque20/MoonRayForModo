"""Validate pre-evaluation GPU Lambert shading without a CPU BSDF oracle."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.film_showcase import scene as showcase
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('build','reference','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--ptx',type=Path,required=True)
    p.add_argument('--threads',type=int,choices=(1,4),default=1)
    p.add_argument('--adaptive',action='store_true')
    p.add_argument('--unsupported',action='store_true',help='Enable native shadow-terminator correction, outside the CUDA shader subset')
    p.add_argument('--diagnostic',action='store_true',help='Repeat reference and complete all cases despite image differences; never converts differences to a pass')
    a=p.parse_args();build,reference,out=(getattr(a,n).resolve() for n in ('build','reference','output'))
    out.mkdir(parents=True,exist_ok=False);report=dict(status='incomplete',runs=[],threads=a.threads,adaptive=a.adaptive,unsupported=a.unsupported,scope='Early bounded Lambert dispatch without duplicate lobe sample evaluation; native integrator remains on its owner')
    try:
        m=json.loads((build/'report.json').read_text());runtime=build/'runtime'
        if m['status']!='built' or digest_file(runtime/'librendering_rndr.dll')!=m['dll_sha256']:raise ValueError('Build drift')
        hashes={**m['source_hashes'],**m['native_hashes']}
        for f,h in hashes.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift')
        ptx=a.ptx.resolve();report['ptx_sha256']=digest_file(ptx)
        report['probe_sha256']=digest_file(Path(__file__));report['build_sha256']=digest_file(build/'report.json');gpu=gpu_identity();report['gpu']=(gpu or '').split(', GPU-')[0]
        locked={str(rt):inventory(rt) for rt in (runtime,reference)}
        original=ROOT/'xpu2/reference/scene.rdla'
        text=original.read_text()+'\nSceneVariables { ["frame"]=0, ["min_frame"]=0, ["max_frame"]=0, ["lock_frame_noise"]=true, ["pixel_samples"]=1 }\n\nUsdPreviewSurface("/modo/material/1") { ["useSpecularWorkflow"]=1, ["specularColor"]=Rgb(0,0,0) }\nSceneVariables { ["shadow_terminator_fix"]=0, ["bsdf_samples"]=3 }\n'
        text=showcase('\n'.join(text.splitlines()));scene=out/'scene.rdla'
        report['fixture_inputs']={str(f.relative_to(ROOT)):digest_file(f) for f in (original,ROOT/'xpu2/film_showcase.py')}
        if a.adaptive:text+='\nSceneVariables { ["sampling_mode"]=2, ["min_adaptive_samples"]=4, ["max_adaptive_samples"]=16, ["target_adaptive_error"]=10 }\n'
        if a.unsupported:text+='\nSceneVariables { ["shadow_terminator_fix"]=1 }\n'
        scene.write_text(text);report['scene_sha256']=digest_file(scene)
        images={};differences=[]
        labels=('reference','reference_repeat','disabled','replace','sentinel','missing','capacity0') if a.diagnostic else ('reference','disabled','replace','sentinel','missing','capacity0')
        if a.adaptive or a.unsupported:labels=('reference','disabled','replace')
        for label in labels:
            folder=out/label;folder.mkdir();rt=reference if label.startswith('reference') else runtime;env=environment(rt,folder)
            for k in list(env):
                if k.startswith('XPU2_'):del env[k]
            enabled=label not in ('reference','reference_repeat','disabled');profile=folder/'paths.jsonl'
            gpu_profile=folder/'gpu.jsonl';early_profile=folder/'early.jsonl'
            if enabled:env.update(XPU2_NATIVE_PATH_RESTORE='deferred',XPU2_NATIVE_PATH_PROFILE=str(profile),XPU2_NATIVE_GPU_PATHS='1',XPU2_NATIVE_GPU_PROFILE=str(gpu_profile),XPU2_NATIVE_EARLY_PROFILE=str(early_profile),XPU2_NATIVE_LAMBERT='execute_sentinel' if label=='sentinel' else 'execute',XPU2_NATIVE_LAMBERT_PTX=str(folder/'missing.ptx' if label=='missing' else ptx),XPU2_NATIVE_LAMBERT_LOG=str(folder/'lambert.jsonl'))
            if label=='capacity0':env['XPU2_QUEUE_CAPACITY']='0'
            if label=='poison':env['XPU2_NATIVE_PATH_POISON']='1'
            cmd=[str(rt/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads',str(a.threads),'-info','-stats',str(folder/'stats.csv')]
            print(label,flush=True);started=time.perf_counter();logpath=folder/'render.log'
            with logpath.open('w') as log:
                done=subprocess.run(cmd,cwd=folder,env=env,stdout=log,stderr=log,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
            check=successful('xpu',a.threads,done.returncode,logpath.read_text(errors='replace'),(folder/'stats.csv').read_text(errors='replace') if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
            row=dict(label=label,execution=check,exit_code=done.returncode,seconds=time.perf_counter()-started,log_sha256=digest_file(logpath));report['runs'].append(row)
            if not check['passed']:raise ValueError('Native render failed: '+label)
            image=read_rgba(rt,folder/'beauty.exr',folder,'raw',env);images[label]=image
            if enabled:
                row['paths']=[json.loads(line) for line in profile.read_text().splitlines()]
                if any(e['captured'] or e['outstanding'] for e in row['paths']):raise ValueError('Duplicate late path dispatch')
                row['gpu']=[json.loads(line) for line in gpu_profile.read_text().splitlines()]
                row['early']=[json.loads(line) for line in early_profile.read_text().splitlines()]
                if len(row['gpu'])!=1 or len(row['early'])!=1:raise ValueError('Missing frame teardown')
                g=row['gpu'][0];e=row['early'][0]
                if g['retained'] or g['cleanup_errors'] or g['timeouts'] or e['timeouts']:raise ValueError('GPU lifetime failed')
                if e['gpu_lanes']!=g['gpu_accepted'] or g['gpu_accepted']!=g['gpu_replaced']:raise ValueError('GPU consumption accounting failed')
                if a.adaptive:
                    if e['submitted_packets'] or e['gpu_lanes']:raise ValueError('Adaptive bypass failed')
                elif a.unsupported or label in ('missing','capacity0'):
                    if e['gpu_lanes'] or not e['fallback_lanes']:raise ValueError('CPU fallback not exercised')
                    if label=='missing' and not g['gpu_errors']:raise ValueError('Missing PTX not exercised')
                    if label=='capacity0' and e['submitted_packets']:raise ValueError('Capacity refusal not exercised')
                elif not(e['gpu_lanes']>0 and e['submitted_packets']>0 and not g['gpu_errors'] and not g['gpu_mismatch']):raise ValueError('GPU-only shading not exercised')
            # One-worker output must stay exact. Four workers retain the existing
            # 1e-6 gate; diagnostic failures remain failures.
            exact=a.threads==1
            row['comparison']=compare_rgba(images['reference'],image,absolute=0 if exact else 1e-6,relative=0 if exact else 1e-6)
            if label=='sentinel' and not a.adaptive:
                row['sentinel_comparison']=compare_rgba(images['replace'],image,absolute=1e-6,relative=1e-6)
                delta=row['sentinel_comparison']
                if delta['exactly_different_pixels']<10 or max(c['maximum_absolute_error'] for c in delta['channels'].values())<1e-4:
                    raise ValueError('Restored throughput did not meaningfully affect native image')
            elif row['comparison']['status']!='passed':
                differences.append(label)
                if not a.diagnostic:raise ValueError('Native image mismatch: '+label)
            (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        for rt in (runtime,reference):verify(rt,locked[str(rt)])
        for f,h in hashes.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift after render')
        for f,h in report['fixture_inputs'].items():
            if digest_file(ROOT/f)!=h:raise ValueError('Fixture input drift')
        if digest_file(ptx)!=report['ptx_sha256']:raise ValueError('PTX drift')
        if gpu_identity()!=gpu:raise ValueError('GPU changed')
        if digest_file(Path(__file__))!=report['probe_sha256']:raise ValueError('Probe changed during run')
        report['image_mismatches']=differences
        report['status']='image_differences' if differences else 'passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return {'passed':0,'image_differences':2}.get(report['status'],1)
if __name__=='__main__':raise SystemExit(main())
