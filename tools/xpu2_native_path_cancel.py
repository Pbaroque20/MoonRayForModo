"""Compare native persistent reference, fresh restoration, and cancelled/reloaded restoration."""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('build','reference','baseline','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();build,reference,baseline,out=(getattr(a,n).resolve() for n in ('build','reference','baseline','output'))
    out.mkdir(parents=True,exist_ok=False);report=dict(status='incomplete',runs=[])
    try:
        m=json.loads((build/'report.json').read_text());runtime=build/'runtime'
        if m['status']!='built' or digest_file(runtime/'librendering_rndr.dll')!=m['dll_sha256']:raise ValueError('Build drift')
        for f,h in {**m['source_hashes'],**m['native_hashes']}.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift')
        b=json.loads((baseline/'report.json').read_text())
        if b['status']!='passed' or b['threads']!=1 or b['adaptive']:raise ValueError('Passed fixed-sample baseline required')
        if b['build_sha256']!=digest_file(build/'report.json'):raise ValueError('Baseline uses a different build')
        report['probe_sha256']=digest_file(Path(__file__));report['baseline_report_sha256']=digest_file(baseline/'report.json')
        scene=baseline/'scene.rdla'
        if digest_file(scene)!=b['scene_sha256']:raise ValueError('Baseline scene drift')
        held={str(rt):inventory(rt) for rt in (runtime,reference)};report['build_sha256']=digest_file(build/'report.json')
        gpu=gpu_identity();report['gpu']=(gpu or '').split(', GPU-')[0]
        longscene=out/'long.rdla';longscene.write_text(scene.read_text()+'\nSceneVariables { ["pixel_samples"]=16 }\n')
        images={};differences=[]
        for label in ('reference','fresh','restart'):
            folder=out/label;folder.mkdir();rt=reference if label=='reference' else runtime
            session=folder/'session';session.mkdir();profile=folder/'paths.jsonl';env=environment(rt,folder)
            env.update(MOONRAY_MODO_SESSION=str(session),MOONRAY_MODO_GENERATION='0')
            if label!='reference':env.update(XPU2_NATIVE_PATH_RESTORE='deferred',XPU2_NATIVE_PATH_PROFILE=str(profile),XPU2_NATIVE_PATH_POISON='1')
            logpath=folder/'render.log';cmd=[str(rt/'moonray.exe'),'-in',str(longscene if label=='restart' else scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')]
            print(label,flush=True)
            with logpath.open('w') as log:
                proc=subprocess.Popen(cmd,cwd=folder,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                def wait(marker):
                    deadline=time.monotonic()+180
                    while marker not in logpath.read_text(errors='replace'):
                        if proc.poll() is not None or time.monotonic()>deadline:raise ValueError(label+': missing '+marker)
                        time.sleep(.005)
                def send(num,mode):
                    pending=session/'pending.txt';pending.write_text('\n'.join([str(num),mode,'',str(scene)])+'\n');pending.replace(session/'command.txt')
                try:
                    if label=='restart':
                        wait('XPU2_PATH_SUSPENDED 1');send(1,'full');wait('@@MODO_SESSION CANCELED 0');wait('@@MODO_SESSION DONE 1');send(2,'quit')
                    else:wait('@@MODO_SESSION DONE 0');send(1,'quit')
                    code=proc.wait(timeout=30)
                finally:
                    if proc.poll() is None:proc.kill();proc.wait(timeout=10)
            logs=logpath.read_text(errors='replace')
            if label=='restart' and '@@MODO_SESSION DONE 0' in logs:raise ValueError('Cancellation arrived too late')
            check=successful('xpu',1,code,logs,(folder/'stats.csv').read_text(errors='replace'),(folder/'beauty.exr').exists())
            row=dict(label=label,execution=check,log_sha256=digest_file(logpath));report['runs'].append(row)
            if not check['passed']:raise ValueError('Persistent native render failed: '+label)
            if label!='reference':
                events=[json.loads(s) for s in profile.read_text().splitlines()];row['frames']=events
                if [e['epoch'] for e in events]!=([1,2] if label=='restart' else [1]):raise ValueError('Frame ownership failed')
                for e in events:
                    if not(e['captured']>0 and e['captured']==e['restored']+e['cancelled'] and e['outstanding']==0 and e['poisoned']==e['captured']):raise ValueError('Path accounting failed')
                if events[-1]['cancelled']:raise ValueError('Completed frame lost paths')
            images[label]=read_rgba(rt,folder/'beauty.exr',folder,'image',env)
            row['comparison']=compare_rgba(images['reference'],images[label],absolute=1e-6,relative=1e-6)
            if row['comparison']['status']!='passed':differences.append(label)
            if label=='restart':row['versus_fresh']=compare_rgba(images['fresh'],images[label],absolute=1e-6,relative=1e-6)
            (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        for rt in (runtime,reference):verify(rt,held[str(rt)])
        for f,h in {**m['source_hashes'],**m['native_hashes']}.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift after test')
        if digest_file(Path(__file__))!=report['probe_sha256']:raise ValueError('Probe changed during run')
        if digest_file(scene)!=b['scene_sha256'] or gpu_identity()!=gpu:raise ValueError('Test identity changed')
        report['image_mismatches']=differences;report['status']='image_differences' if differences else 'passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return {'passed':0,'image_differences':2}.get(report['status'],1)
if __name__=='__main__':raise SystemExit(main())
