"""Validate native child-path reconstruction and deferred queue resumption."""
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
    p.add_argument('--threads',type=int,choices=(1,4),default=1)
    p.add_argument('--adaptive',action='store_true')
    p.add_argument('--diagnostic',action='store_true',help='Repeat reference and complete all cases despite image differences; never converts differences to a pass')
    a=p.parse_args();build,reference,out=(getattr(a,n).resolve() for n in ('build','reference','output'))
    out.mkdir(parents=True,exist_ok=False);report=dict(status='incomplete',runs=[],threads=a.threads,adaptive=a.adaptive,scope='Native first diffuse child-bounce restoration; shading remains synchronous before this boundary')
    try:
        m=json.loads((build/'report.json').read_text());runtime=build/'runtime'
        if m['status']!='built' or digest_file(runtime/'librendering_rndr.dll')!=m['dll_sha256']:raise ValueError('Build drift')
        hashes={**m['source_hashes'],**m['native_hashes']}
        for f,h in hashes.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift')
        report['probe_sha256']=digest_file(Path(__file__));report['build_sha256']=digest_file(build/'report.json');gpu=gpu_identity();report['gpu']=(gpu or '').split(', GPU-')[0]
        locked={str(rt):inventory(rt) for rt in (runtime,reference)}
        original=ROOT/'xpu2/reference/scene.rdla'
        text=original.read_text()+'\nSceneVariables { ["frame"]=0, ["min_frame"]=0, ["max_frame"]=0, ["lock_frame_noise"]=true, ["pixel_samples"]=1 }\n\nUsdPreviewSurface("/modo/material/1") { ["useSpecularWorkflow"]=1, ["specularColor"]=Rgb(0,0,0) }\nSceneVariables { ["shadow_terminator_fix"]=0, ["bsdf_samples"]=3 }\n'
        text=showcase('\n'.join(text.splitlines()));scene=out/'scene.rdla'
        report['fixture_inputs']={str(f.relative_to(ROOT)):digest_file(f) for f in (original,ROOT/'xpu2/film_showcase.py')}
        if a.adaptive:text+='\nSceneVariables { ["sampling_mode"]=2, ["min_adaptive_samples"]=4, ["max_adaptive_samples"]=16, ["target_adaptive_error"]=10 }\n'
        scene.write_text(text);report['scene_sha256']=digest_file(scene)
        images={};differences=[]
        labels=('reference','reference_repeat','disabled','immediate','deferred','poison','sentinel') if a.diagnostic else ('reference','disabled','immediate','deferred','poison','sentinel')
        for label in labels:
            folder=out/label;folder.mkdir();rt=reference if label.startswith('reference') else runtime;env=environment(rt,folder)
            for k in list(env):
                if k.startswith('XPU2_'):del env[k]
            enabled=label not in ('reference','reference_repeat','disabled');profile=folder/'paths.jsonl'
            if enabled:env.update(XPU2_NATIVE_PATH_RESTORE='deferred' if label=='poison' else label,XPU2_NATIVE_PATH_PROFILE=str(profile))
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
                events=[json.loads(s) for s in profile.read_text().splitlines()];row['paths']=events
                if len(events)!=1:raise ValueError('Missing frame teardown')
                e=events[0]
                if e['captured']!=e['restored'] or e['cancelled'] or e['outstanding'] or e['peak_owner_paths']>4096:raise ValueError('Native path accounting failed')
                if a.adaptive:
                    if e['captured'] or not e['fallback_batches']:raise ValueError('Adaptive bypass failed')
                elif not e['restored']:raise ValueError('No native child path restored')
                if label=='poison' and e['poisoned']!=e['captured']:raise ValueError('Original state poison not exercised')
            # Deferred queue order can change float summation. Immediate single-
            # worker reconstruction must be exact; deferred uses the established
            # 1e-6 diagnostic RGB bound, declared before any comparison.
            exact=a.threads==1 and (label in ('reference','disabled','immediate') or a.adaptive)
            row['comparison']=compare_rgba(images['reference'],image,absolute=0 if exact else 1e-6,relative=0 if exact else 1e-6)
            if label=='sentinel' and not a.adaptive:
                row['sentinel_comparison']=compare_rgba(images['deferred'],image,absolute=1e-6,relative=1e-6)
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
        if gpu_identity()!=gpu:raise ValueError('GPU changed')
        if digest_file(Path(__file__))!=report['probe_sha256']:raise ValueError('Probe changed during run')
        report['image_mismatches']=differences
        report['status']='image_differences' if differences else 'passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return {'passed':0,'image_differences':2}.get(report['status'],1)
if __name__=='__main__':raise SystemExit(main())
