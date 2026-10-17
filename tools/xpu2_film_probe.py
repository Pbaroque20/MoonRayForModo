"""Render native images with live GPU contribution replacement and explicit controls."""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2.film_evidence import validate_profile,compare_windows
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('build','base','output'):p.add_argument('--'+key,required=True,type=Path)
    p.add_argument('--showcase',action='store_true',help='Use a framed sphere, ground and distant key; run reference/audit/fast')
    p.add_argument('--fused',action='store_true',help='Compare separate vs fused live Lambert/contribution dispatch')
    a=p.parse_args();build,base,out=a.build.resolve(),a.base.resolve(),a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    report=dict(status='incomplete',runs=[],gpu=gpu_identity(),scope='Live native image with GPU Lambert and contribution arithmetic; resident CPU path, CPU lights, native visibility and film')
    try:
        manifest=json.loads((build/'report.json').read_text());assert manifest['status']=='built'
        for name,wanted in manifest['files'].items():
            if digest_file(build/name)!=wanted:raise ValueError('Build drift')
        report['build_manifest_sha256']=digest_file(build/'report.json')
        if a.fused and not manifest.get('fused'):raise ValueError('Fused-capable build required')
        report['fused']=a.fused
        runtime=build/'runtime';lock=inventory(runtime);reference=base/'control';reference_lock=inventory(reference)
        lambert=ROOT/'test-results/xpu2-ray-image-final/sampler.ptx';meta=json.loads((lambert.parent/'report.json').read_text())
        if meta['status']!='passed' or meta['ptx_sha256']!=digest_file(lambert):raise ValueError('Lambert PTX drift')
        report['lambert_ptx_sha256']=digest_file(lambert)
        original=ROOT/'test-results/xpu2-owned-contribution-validation/control/scene.rdla'
        old=json.loads((original.parent.parent/'report.json').read_text())
        if old['status']!='passed' or digest_file(original)!=old['renders'][0]['scene_sha256']:raise ValueError('Reference scene drift')
        scene=out/'scene.rdla'
        if a.showcase:
            from xpu2.film_showcase import scene as showcase
            scene.write_text(showcase(original.read_text()),encoding='utf-8')
        else:scene.write_bytes(original.read_bytes())
        report['scene_sha256']=digest_file(scene);report['showcase']=a.showcase
        images={}
        cases=('reference','shading','audit','fast_packet','fast','repeat') if a.showcase else ('reference','disabled','shading','audit','fast','repeat','sentinel','missing')
        if a.fused:cases=('reference','separate','audit','fast','repeat') if a.showcase else ('reference','disabled','separate','audit','fast','repeat','sentinel','missing','bad_shader')
        for label in cases:
            fused=a.fused and label not in ('reference','disabled','separate')
            folder=out/label;folder.mkdir();rt=reference if label=='reference' else runtime;env=environment(rt,folder)
            if label not in ('reference','disabled'):
                env.update(XPU2_NATIVE_LAMBERT='replace',XPU2_NATIVE_LAMBERT_PTX=str(lambert),XPU2_NATIVE_BATCH_WIDTH='16',XPU2_WINDOW_DISPATCH='1',XPU2_ASYNC_TRANSFERS='1',XPU2_PACKED_READBACK='1',XPU2_SHADER_AUDIT='1',XPU2_NATIVE_LIGHT_OVERLAP='1',XPU2_PROFILE_FILE=str(folder/'shading.json'),XPU2_PROFILE_QUIET='1')
            if label in ('separate','audit','fast_packet','fast','repeat','sentinel','missing','bad_shader'):
                mode='fast' if label in ('separate','fast_packet','repeat','missing','bad_shader') else label
                env.update(XPU2_FILM_CONTRIBUTION=mode,XPU2_FILM_PTX=str(folder/'missing.ptx' if label=='missing' else build/'film.ptx'),XPU2_FILM_PROFILE=str(folder/'film.json'))
            if label=='fast_packet':env['XPU2_FILM_WINDOW']='1'
            if fused:env['XPU2_FUSED_FILM']='1'
            if label=='bad_shader':env['XPU2_FUSED_BAD_REFERENCE']='1'
            print(label,flush=True);start=time.perf_counter()
            with (folder/'render.log').open('w') as log:
                r=subprocess.run([str(rt/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')],cwd=folder,env=env,stdout=log,stderr=log,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
            elapsed=time.perf_counter()-start
            check=successful('xpu',1,r.returncode,(folder/'render.log').read_text(errors='replace'),(folder/'stats.csv').read_text() if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
            row=dict(label=label,wall_seconds=elapsed,execution=check,log_sha256=digest_file(folder/'render.log'));report['runs'].append(row)
            if not check['passed']:raise ValueError('Native render failed '+label)
            images[label]=read_rgba(rt,folder/'beauty.exr',folder,'raw',env)
            comparison=compare_rgba(images['reference'],images[label]);row['image']=comparison
            if label=='sentinel':
                if not comparison['exactly_different_pixels']:raise ValueError('GPU contributions did not reach film')
            elif comparison['status']!='passed':raise ValueError('Film parity failed '+label)
            if label not in ('reference','disabled') and not fused:
                profile=json.loads((folder/'shading.json').read_text());row['shading_profile']=profile
                if profile['errors'] or profile['mismatch'] or not profile['replaced']:raise ValueError('GPU Lambert missing or invalid')
            if label in ('separate','audit','fast_packet','fast','repeat','sentinel','missing','bad_shader'):
                profile=json.loads((folder/'film.json').read_text());row['contribution_profile']=profile
                from xpu2.fused_film_evidence import validate_fused
                if fused:row['contribution_validation']=validate_fused(profile,'fast' if label=='repeat' else label)
                else:row['contribution_validation']=validate_profile(profile,'fast' if label in ('repeat','fast_packet','separate') else label)
                if fused and (folder/'shading.json').exists():raise ValueError('Separate GPU shading queue unexpectedly ran')
            (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        if a.showcase and not a.fused:
            profiles={r['label']:r.get('contribution_profile') for r in report['runs']}
            report['window_validation']=compare_windows(profiles['fast_packet'],profiles['fast'])
        if a.fused:
            from xpu2.fused_film_evidence import compare_fused
            profiles={r['label']:r.get('contribution_profile') for r in report['runs']}
            report['fusion_validation']=compare_fused(profiles['separate'],profiles['fast'])
        fast=out/'fast';env=environment(runtime,fast)
        display=subprocess.run([str(runtime/'oiiotool.exe'),str(fast/'beauty.exr'),'--ch','R,G,B','--powc','0.45454545','-d','uint8','-o',str(out/'gpu-image.png')],env=env,capture_output=True,text=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
        if display.returncode:raise ValueError('Display conversion failed: '+display.stderr)
        verify(runtime,lock);verify(reference,reference_lock)
        if gpu_identity()!=report['gpu']:raise ValueError('Device drift')
        report.update(status='passed',display='gamma 2.2 preview; validation uses raw linear RGBA',speedup_established=False)
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
