"""Render isolated persistent scenes through real native mutation/teardown hooks."""
import argparse,json,os,shutil,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2.native_scene_drain import validate,validate_cancel
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','reference','output'):p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args();build,reference,out=a.build.resolve(),a.reference.resolve(),a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(status='incomplete',sessions=[],images={})
    try:
        manifest=json.loads((build/'report.json').read_text());runtime=build/'runtime'
        if manifest['status']!='built' or digest_file(runtime/'librendering_rndr.dll')!=manifest['dll_sha256']:raise ValueError('Build drift')
        held=inventory(runtime);gpu=gpu_identity();report.update(gpu=gpu,build_manifest_sha256=digest_file(build/'report.json'))
        original=(ROOT/'test-results/xpu2-origins/unit/scene.rdla').read_text();scene=out/'scene.rdla';scene.write_text(original)
        delta=out/'move.rdla';delta.write_text('RdlMeshGeometry("/modo/mesh/0") { ["node_xform"] = Mat4(1,0,0,0,0,1,0,0,0,0,1,0,0.2,0,0,1) }\n')
        longscene=out/'cancel.rdla';longscene.write_text(original+'\nSceneVariables { ["pixel_samples"]=16 }\n')
        images={}
        for label in ('reference','control','probe','cancel'):
            folder=out/label;folder.mkdir();session=folder/'session';session.mkdir();rt=reference if label=='reference' else runtime
            env=environment(rt,folder);env.update(MOONRAY_MODO_SESSION=str(session),MOONRAY_MODO_GENERATION='0')
            if label in ('probe','cancel'):env.update(XPU2_NATIVE_SCENE_DRAIN='1',XPU2_TRACE_FILE=str(folder/'trace.jsonl'))
            command=[str(rt/'moonray.exe'),'-in',str(longscene if label=='cancel' else scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')]
            print(label,flush=True)
            logpath=folder/'render.log'
            with logpath.open('w') as log:
                process=subprocess.Popen(command,cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
                def wait(marker,path=logpath,timeout=180):
                    deadline=time.monotonic()+timeout
                    while time.monotonic()<deadline:
                        if path.exists() and marker in path.read_text(errors='replace'):return
                        if process.poll() is not None:raise ValueError(label+' exited before '+marker)
                        time.sleep(.02)
                    raise TimeoutError(label+' waiting for '+marker)
                def send(id,mode,path=''):
                    pending=session/'pending.txt';pending.write_text('\n'.join([str(id),mode,str(path),str(scene)])+'\n');pending.replace(session/'command.txt')
                try:
                    if label=='cancel':
                        wait('"event":"captured"',folder/'trace.jsonl');send(1,'quit');wait('@@MODO_SESSION CANCELED 0')
                    else:
                        frames=[]
                        for frame in range(3):
                            wait('@@MODO_SESSION DONE '+str(frame));saved=folder/('frame-'+str(frame)+'.exr');shutil.copy2(folder/'beauty.exr',saved);frames.append(saved)
                            if frame==0:send(1,'delta',delta)
                            elif frame==1:send(2,'full')
                            else:send(3,'quit')
                    code=process.wait(timeout=30)
                finally:
                    if process.poll() is None:process.kill();process.wait(timeout=10)
            logs=logpath.read_text(errors='replace');stats=(folder/'stats.csv').read_text(errors='replace')
            check=(validate_cancel(logs,code,validate((folder/'trace.jsonl').read_text(),1)) if label=='cancel' else successful('xpu',1,code,logs,stats,(folder/'beauty.exr').exists()))
            if not check['passed']:raise ValueError('Invalid native XPU session '+label)
            entry=dict(label=label,execution=check,exit_code=code,log_sha256=digest_file(logpath));report['sessions'].append(entry)
            if label in ('probe','cancel'):
                entry['lifetime']=validate((folder/'trace.jsonl').read_text(),1 if label=='cancel' else 3,label=='probe');entry['trace_sha256']=digest_file(folder/'trace.jsonl')
            if label!='cancel':images[label]=[read_rgba(rt,f,folder,'frame-'+str(i),env) for i,f in enumerate(frames)]
        for label in ('control','probe'):
            report['images'][label]=[compare_rgba(ref,img) for ref,img in zip(images['reference'],images[label])]
            if any(r['status']!='passed' for r in report['images'][label]):raise ValueError('Native hooks changed final pixels')
        report['delta_image_change']=compare_rgba(images['reference'][0],images['reference'][1])['exactly_different_pixels']
        if not report['delta_image_change']:raise ValueError('Geometry delta had no visible effect')
        if compare_rgba(images['reference'][0],images['reference'][2])['status']!='passed':raise ValueError('Full reload failed to restore scene')
        verify(runtime,held)
        if gpu!=gpu_identity():raise ValueError('GPU drift')
        report['status']='passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
