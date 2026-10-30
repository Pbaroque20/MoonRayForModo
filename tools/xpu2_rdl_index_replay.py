"""Validate original RDLA parity or replay a tested native index on another scene.

Uses the already-built isolated native adapter. Does not install or launch Modo.
"""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('build','runtime','scene','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--reference-image',type=Path,help='Only compare original RDLA against an existing indexed image')
    p.add_argument('--scene-lock',type=Path,help='Verify a previously pinned dense/reference scene')
    a=p.parse_args();build,runtime,scene,out=(getattr(a,k).resolve() for k in ('build','runtime','scene','output'))
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='incomplete',scope='Exact single-worker native XPU scene-index validation',renders=[])
    try:
        manifest=json.loads((build/'report.json').read_text());assert manifest['status']=='passed'
        exe=build/'rdl-index.exe'
        if digest_file(exe)!=manifest['executable_sha256']:raise ValueError('Native adapter binary drift')
        for path,expected in manifest['source_hashes'].items():
            if digest_file(Path(path))!=expected:raise ValueError('Native adapter/source input drift: '+path)
        if a.scene_lock:
            lock=json.loads(a.scene_lock.read_text())
            if digest_file(scene)!=lock['contract']['scene_sha256']:raise ValueError('Pinned scene drift')
        print('pin runtime',flush=True);locked=inventory(runtime);gpu=gpu_identity()
        report.update(build_manifest_sha256=digest_file(build/'report.json'),scene_sha256=digest_file(scene),gpu=gpu,
                      runtime_inventory=locked)
        def render(label,path):
            folder=out/label;folder.mkdir();env=environment(runtime,folder)
            print('render '+label,flush=True);started=time.perf_counter()
            with (folder/'render.log').open('w') as log:
                run=subprocess.run([str(runtime/'moonray.exe'),'-in',str(path),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')],cwd=folder,env=env,stdout=log,stderr=log,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
            check=successful('xpu',1,run.returncode,(folder/'render.log').read_text(errors='replace'),(folder/'stats.csv').read_text() if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
            row=dict(label=label,execution=check,wall_seconds=time.perf_counter()-started,scene_sha256=digest_file(path));report['renders'].append(row)
            if not check['passed']:raise ValueError('XPU render failed: '+label)
            image=read_rgba(runtime,folder/'beauty.exr',folder,'raw',env);row['image_sha256']=image['sha256'];return image
        original=render('original',scene)
        if a.reference_image:
            indexed=read_rgba(runtime,a.reference_image.resolve(),out,'existing-indexed',environment(runtime,out))
            report['original_comparison']=compare_rgba(original,indexed)
            report['indexed_image_sha256']=indexed['sha256']
            if report['original_comparison']['status']!='passed':raise ValueError('Original RDLA differs from indexed image')
        else:
            print('replay native index',flush=True)
            env=environment(runtime,out)
            done=subprocess.run([str(exe),str(scene),env['RDL2_DSO_PATH'],str(out)],env=env,cwd=out,capture_output=True,text=True,timeout=180,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/'probe.log').write_text(done.stdout+done.stderr,encoding='utf-8')
            if done.returncode:raise ValueError('Native replay failed: '+done.stderr[-1600:])
            report['native']=json.loads(done.stdout)
            if report['native'].get('status')!='passed':raise ValueError('Incomplete native replay')
            last=None
            for stage in ('initial','transform','material','deformation','binding','unbinding'):
                source_image=render(stage+'-source',out/(stage+'-source.rdlb'))
                indexed=render(stage+'-indexed',out/(stage+'-indexed.rdlb'))
                result=compare_rgba(source_image,indexed);report['renders'][-1]['image_comparison']=result
                if result['status']!='passed':raise ValueError('Indexed image differs: '+stage)
                if stage=='initial':
                    report['original_comparison']=compare_rgba(original,indexed)
                    if report['original_comparison']['status']!='passed':raise ValueError('Initial indexed image differs from original RDLA')
                elif last is not None:
                    changed=compare_rgba(last,indexed)['exactly_different_pixels']
                    report['renders'][-1]['edited_pixels']=changed
                    if not changed:raise ValueError('Fixture edit was not visible: '+stage)
                last=indexed
                (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
        verify(runtime,locked)
        if gpu_identity()!=gpu or digest_file(exe)!=manifest['executable_sha256']:raise ValueError('Device/binary drift')
        report['status']='passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
