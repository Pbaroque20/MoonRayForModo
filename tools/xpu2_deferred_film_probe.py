"""Validate native completed-radiance suspension and original film resumption.

One worker requires exact RGBA; four-worker tests retain the previously declared
1e-6 absolute/relative diagnostic bound. This is not resumable shading validation.
"""
import argparse,json,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('build','reference','output'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--threads',type=int,choices=(1,4),default=1)
    p.add_argument('--crypto',action='store_true');p.add_argument('--adaptive',action='store_true');p.add_argument('--persistent',action='store_true')
    a=p.parse_args();build,reference,out=(getattr(a,n).resolve() for n in ('build','reference','output'))
    out.mkdir(parents=True,exist_ok=False);report=dict(status='incomplete',runs=[],threads=a.threads,adaptive=a.adaptive,crypto=a.crypto,persistent=a.persistent,scope='Native terminal beauty continuation; no shading migration or GPU shading acceleration')
    try:
        m=json.loads((build/'report.json').read_text());runtime=build/'runtime'
        if m['status']!='built' or digest_file(runtime/'librendering_rndr.dll')!=m['dll_sha256']:raise ValueError('Build drift')
        for f,h in m['source_hashes'].items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift')
        report['build_sha256']=digest_file(build/'report.json');gpu=gpu_identity();report['gpu']=(gpu or '').split(', GPU-')[0]
        locked={str(rt):inventory(rt) for rt in (runtime,reference)}
        original=ROOT/'test-results/xpu2-owned-contribution-validation/control/scene.rdla'
        text=original.read_text();scene=out/'scene.rdla'
        if a.adaptive:text+='\nSceneVariables { ["sampling_mode"]=2, ["min_adaptive_samples"]=4, ["max_adaptive_samples"]=16, ["target_adaptive_error"]=10 }\n'
        if a.crypto:text+='\nRenderOutput("/crypto") { ["result"]=13, ["file_name"]="crypto.exr" }\n'
        scene.write_text(text);report['scene_sha256']=digest_file(scene)
        images={};cases=['reference','disabled','deferred','failure','invalid','sentinel'] if not a.persistent else ['reference','deferred']
        for label in cases:
            folder=out/label;folder.mkdir();rt=reference if label=='reference' else runtime;env=environment(rt,folder)
            enabled=label not in ('reference','disabled');profile=folder/'continuations.jsonl'
            if enabled:env.update(XPU2_DEFERRED_FILM='1',XPU2_DEFERRED_PROFILE=str(profile))
            if label=='failure':env['XPU2_DEFERRED_FAIL']='1'
            if label=='invalid':env['XPU2_DEFERRED_INVALID']='1'
            if label=='sentinel':env['XPU2_DEFERRED_SENTINEL']='1'
            session=folder/'session'
            if a.persistent:session.mkdir();env.update(MOONRAY_MODO_SESSION=str(session),MOONRAY_MODO_GENERATION='0')
            cmd=[str(rt/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads',str(a.threads),'-info','-stats',str(folder/'stats.csv')]
            logpath=folder/'render.log';saved=[];print(label,flush=True);started=time.perf_counter()
            with logpath.open('w') as log:
                proc=subprocess.Popen(cmd,cwd=folder,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                try:
                    if a.persistent:
                        def send(num,mode):
                            pending=session/'pending.txt';pending.write_text('\n'.join([str(num),mode,'',str(scene)])+'\n');pending.replace(session/'command.txt')
                        for frame in range(3):
                            if frame:send(frame,'full')
                            deadline=time.monotonic()+180
                            while '@@MODO_SESSION DONE '+str(frame)+'\n' not in logpath.read_text(errors='replace'):
                                if proc.poll() is not None or time.monotonic()>deadline:raise ValueError('Frame did not complete')
                                time.sleep(.02)
                            save=folder/('frame'+str(frame)+'.exr');shutil.copy2(folder/'beauty.exr',save);saved.append(save)
                        send(3,'quit');code=proc.wait(timeout=30)
                    else:code=proc.wait(timeout=180);saved=[folder/'beauty.exr']
                finally:
                    if proc.poll() is None:proc.kill();proc.wait(timeout=10)
            check=successful('xpu',a.threads,code,logpath.read_text(errors='replace'),(folder/'stats.csv').read_text(errors='replace') if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
            row=dict(label=label,execution=check,exit_code=code,seconds=time.perf_counter()-started,log_sha256=digest_file(logpath));report['runs'].append(row)
            if not check['passed']:raise ValueError('Native render failed: '+label)
            images[label]=[read_rgba(rt,f,folder,f.stem,env) for f in saved]
            if enabled:
                events=[json.loads(s) for s in profile.read_text().splitlines()];row['continuations']=events
                if len(events)!=len(saved):raise ValueError('Missing frame teardown')
                for i,e in enumerate(events):
                    if a.crypto and e['fallback_batches']==0:raise ValueError('Native handle bypass not exercised')
                    if a.adaptive and (e['jobs'] or not e['fallback_batches']):raise ValueError('Adaptive native fallback failed')
                    if not(e['epoch']==i+1 and (e['jobs']>0 or a.adaptive or a.crypto) and e['jobs']==e['resumed_jobs'] and e['suspended_samples']==e['resumed_samples'] and e['outstanding']==e['revoked_jobs']==0 and e['peak_jobs']<=32 and e['peak_bytes']<=8*1024*1024):raise ValueError('Film retirement accounting failed')
                    expected_failed=e['jobs'] if label in ('failure','invalid') else 0
                    if e['failed_jobs']!=expected_failed:raise ValueError('Fallback accounting failed')
            elif profile.exists():raise ValueError('Feature unexpectedly enabled')
            row['comparisons']=[compare_rgba(ref,img,absolute=0 if a.threads==1 else 1e-6,relative=0 if a.threads==1 else 1e-6) for ref,img in zip(images['reference'],images[label])]
            if label=='sentinel' and not a.adaptive and any(e['jobs'] for e in row['continuations']):
                if not row['comparisons'][0]['exactly_different_pixels']:raise ValueError('Sentinel did not reach native film')
            elif any(c['status']!='passed' for c in row['comparisons']):raise ValueError('Image mismatch: '+label)
            (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        for rt in (runtime,reference):verify(rt,locked[str(rt)])
        if gpu_identity()!=gpu:raise ValueError('GPU changed')
        report['status']='passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
