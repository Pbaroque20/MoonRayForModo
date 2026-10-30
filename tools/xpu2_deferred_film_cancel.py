"""Cancel a native XPU frame with deferred film work, then reload and compare."""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('build','baseline','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();build,baseline,out=(getattr(a,n).resolve() for n in ('build','baseline','output'))
    out.mkdir(parents=True,exist_ok=False);report=dict(status='incomplete')
    try:
        m=json.loads((build/'report.json').read_text());runtime=build/'runtime'
        if m['status']!='built' or digest_file(runtime/'librendering_rndr.dll')!=m['dll_sha256']:raise ValueError('Build drift')
        for f,h in m['source_hashes'].items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift')
        b=json.loads((baseline/'report.json').read_text())
        if b['status']!='passed' or not b['persistent'] or b['threads']!=1:raise ValueError('Passed persistent baseline required')
        scene=baseline/'scene.rdla'
        if digest_file(scene)!=b['scene_sha256']:raise ValueError('Baseline scene drift')
        original=baseline/'reference/frame0.exr';wanted=b['runs'][0]['label'];assert wanted=='reference'
        held=inventory(runtime);report['build_sha256']=digest_file(build/'report.json')
        longscene=out/'long.rdla';longscene.write_text(scene.read_text()+'\nSceneVariables { ["pixel_samples"]=16 }\n')
        session=out/'session';session.mkdir();profile=out/'continuations.jsonl';env=environment(runtime,out)
        env.update(MOONRAY_MODO_SESSION=str(session),MOONRAY_MODO_GENERATION='0',XPU2_DEFERRED_FILM='1',XPU2_DEFERRED_PROFILE=str(profile),XPU2_DEFERRED_DELAY_MS='50')
        logpath=out/'render.log';cmd=[str(runtime/'moonray.exe'),'-in',str(longscene),'-out',str(out/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(out/'stats.csv')]
        with logpath.open('w') as log:
            proc=subprocess.Popen(cmd,cwd=out,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            def wait(marker):
                deadline=time.monotonic()+180
                while marker not in logpath.read_text(errors='replace'):
                    if proc.poll() is not None or time.monotonic()>deadline:raise ValueError('Missing '+marker)
                    time.sleep(.005)
            def send(num,mode):
                pending=session/'pending.txt';pending.write_text('\n'.join([str(num),mode,'',str(scene)])+'\n');pending.replace(session/'command.txt')
            try:
                wait('XPU2_FILM_SUSPENDED 1');send(1,'full');wait('@@MODO_SESSION CANCELED 0');wait('@@MODO_SESSION DONE 1');send(2,'quit');code=proc.wait(timeout=30)
            finally:
                if proc.poll() is None:proc.kill();proc.wait(timeout=10)
        logs=logpath.read_text(errors='replace')
        if '@@MODO_SESSION DONE 0' in logs:raise ValueError('Cancellation arrived too late')
        check=successful('xpu',1,code,logs,(out/'stats.csv').read_text(errors='replace'),(out/'beauty.exr').exists());report['execution']=check
        if not check['passed']:raise ValueError('Restarted native render failed')
        events=[json.loads(s) for s in profile.read_text().splitlines()];report['frames']=events
        if len(events)!=2 or [s['epoch'] for s in events]!=[1,2]:raise ValueError('Frame ownership failed')
        for e in events:
            if not(e['jobs']>0 and e['jobs']==e['resumed_jobs'] and e['suspended_samples']==e['resumed_samples'] and e['outstanding']==e['failed_jobs']==e['revoked_jobs']==0):raise ValueError('Cancellation did not drain')
        ref=read_rgba(runtime,original,out,'reference',env);actual=read_rgba(runtime,out/'beauty.exr',out,'restart',env)
        report['image']=compare_rgba(ref,actual)
        if report['image']['status']!='passed':raise ValueError('Old-frame contamination or restart mismatch')
        report['log_sha256']=digest_file(logpath);verify(runtime,held);report['status']='passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
