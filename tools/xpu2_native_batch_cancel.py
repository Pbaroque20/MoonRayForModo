"""Validate early GPU shading across persistent frames and cancel/reload."""
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
    p.add_argument('--ptx',type=Path,required=True)
    p.add_argument('--wait-timeout',type=int,default=180,help='Bounded session-marker wait in seconds')
    a=p.parse_args();build,reference,baseline,out=(getattr(a,n).resolve() for n in ('build','reference','baseline','output'))
    out.mkdir(parents=True,exist_ok=False);report=dict(status='incomplete',runs=[],wait_timeout=a.wait_timeout)
    try:
        if not 1<=a.wait_timeout<=900:raise ValueError('Wait timeout must be between 1 and 900 seconds')
        ptx=a.ptx.resolve();report['ptx_sha256']=digest_file(ptx)
        m=json.loads((build/'report.json').read_text());runtime=build/'runtime'
        if m['status']!='built' or digest_file(runtime/'librendering_rndr.dll')!=m['dll_sha256']:raise ValueError('Build drift')
        for f,h in {**m['source_hashes'],**m['native_hashes']}.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift')
        b=json.loads((baseline/'report.json').read_text())
        if b['status']!='passed' or b['threads']!=1 or b.get('adaptive',False):raise ValueError('Passed fixed-sample baseline required')
        if b['source_hashes'][str(build/'report.json')]!=digest_file(build/'report.json'):raise ValueError('Baseline uses a different build')
        report['probe_sha256']=digest_file(Path(__file__));report['baseline_report_sha256']=digest_file(baseline/'report.json')
        scene=baseline/'scene.rdla'
        scene_hash=digest_file(scene)
        if not any(Path(f).suffix=='.rdla' and h==scene_hash for f,h in b['source_hashes'].items()):raise ValueError('Baseline scene drift')
        held={str(rt):inventory(rt) for rt in (runtime,reference)};report['build_sha256']=digest_file(build/'report.json')
        gpu=gpu_identity();report['gpu']=(gpu or '').split(', GPU-')[0]
        longscene=out/'long.rdla';longscene.write_text(scene.read_text()+'\nSceneVariables { ["pixel_samples"]=16 }\n')
        images={};differences=[]
        for label in ('reference','fresh','restart'):
            folder=out/label;folder.mkdir();rt=reference if label=='reference' else runtime
            session=folder/'session';session.mkdir();profile=folder/'paths.jsonl';env=environment(rt,folder)
            for key in list(env):
                if key.startswith('XPU2_'):del env[key]
            env.update(MOONRAY_MODO_SESSION=str(session),MOONRAY_MODO_GENERATION='0')
            gpu_profile=folder/'gpu.jsonl';early_profile=folder/'early.jsonl';queue_profile=folder/'queue.jsonl'
            if label!='reference':env.update(XPU2_NATIVE_PATH_RESTORE='deferred',XPU2_NATIVE_PATH_PROFILE=str(profile),XPU2_NATIVE_PATH_POISON='1',XPU2_NATIVE_GPU_PATHS='1',XPU2_GROUP_PACKETS='1',XPU2_INFLIGHT_BATCHES='2',XPU2_TILE_BATCH_LIMIT='16',XPU2_NATIVE_FLIGHT_PROFILE=str(folder/'flight.jsonl'),XPU2_NATIVE_GPU_PROFILE=str(gpu_profile),XPU2_NATIVE_EARLY_PROFILE=str(early_profile),XPU2_QUEUE_LOG=str(queue_profile),XPU2_NATIVE_LAMBERT='execute',XPU2_NATIVE_LAMBERT_PTX=str(ptx),XPU2_QUEUE_COALESCE_US='1000')
            logpath=folder/'render.log';cmd=[str(rt/'moonray.exe'),'-in',str(longscene if label=='restart' else scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')]
            print(label,flush=True)
            with logpath.open('w') as log:
                proc=subprocess.Popen(cmd,cwd=folder,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                def wait(marker,path=logpath):
                    deadline=time.monotonic()+a.wait_timeout
                    while not path.exists() or marker not in path.read_text(errors='replace'):
                        if proc.poll() is not None or time.monotonic()>deadline:raise ValueError(label+': missing '+marker)
                        time.sleep(.005)
                def send(num,mode):
                    pending=session/'pending.txt';pending.write_text('\n'.join([str(num),mode,'',str(scene)])+'\n');pending.replace(session/'command.txt')
                try:
                    if label=='restart':
                        wait('"submitted":1,',queue_profile);send(1,'full');wait('@@MODO_SESSION CANCELED 0');wait('@@MODO_SESSION DONE 1');send(2,'quit')
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
                row['frames']=[json.loads(line) for line in profile.read_text().splitlines()]
                expected=[1,2] if label=='restart' else [1]
                if [e['epoch'] for e in row['frames']]!=expected:raise ValueError('Frame ownership failed')
                if any(e['captured'] or e['outstanding'] for e in row['frames']):raise ValueError('Duplicate late path dispatch')
                row['gpu']=[json.loads(line) for line in gpu_profile.read_text().splitlines()]
                row['early']=[json.loads(line) for line in early_profile.read_text().splitlines()]
                if [g['epoch'] for g in row['gpu']]!=expected or len(row['early'])!=len(expected):raise ValueError('Missing GPU epoch')
                for g,e in zip(row['gpu'],row['early']):
                    if g['retained'] or g['cleanup_errors'] or g['timeouts'] or e['timeouts'] or g['gpu_errors']:raise ValueError('GPU lifetime failed')
                row['flights']=[json.loads(line) for line in (folder/'flight.jsonl').read_text().splitlines()]
                if len(row['flights'])!=len(expected) or any(f['submitted']!=f['retired'] or f['slots']!=2 for f in row['flights']):raise ValueError('Flight epoch drain failed')
                if not row['early'][-1]['gpu_lanes']:raise ValueError('Completed frame did not use GPU')
                if row['early'][-1]['gpu_lanes']!=row['gpu'][-1]['gpu_accepted']:raise ValueError('Completed-frame consumption accounting failed')
            images[label]=read_rgba(rt,folder/'beauty.exr',folder,'image',env)
            row['comparison']=compare_rgba(images['reference'],images[label],absolute=1e-6,relative=1e-6)
            if row['comparison']['status']!='passed':differences.append(label)
            if label=='restart':row['versus_fresh']=compare_rgba(images['fresh'],images[label],absolute=1e-6,relative=1e-6)
            (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        for rt in (runtime,reference):verify(rt,held[str(rt)])
        for f,h in {**m['source_hashes'],**m['native_hashes']}.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift after test')
        if digest_file(Path(__file__))!=report['probe_sha256']:raise ValueError('Probe changed during run')
        if digest_file(scene)!=scene_hash or gpu_identity()!=gpu:raise ValueError('Test identity changed')
        if digest_file(ptx)!=report['ptx_sha256']:raise ValueError('PTX drift')
        report['image_mismatches']=differences;report['status']='image_differences' if differences else 'passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return {'passed':0,'image_differences':2}.get(report['status'],1)
if __name__=='__main__':raise SystemExit(main())
