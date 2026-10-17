"""A/B native timing probe; exact validation stays enabled in quiet mode."""
import argparse,hashlib,json,struct,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import inventory,verify,digest_file
from xpu2.images import read_rgba,compare_rgba
from xpu2 import native_integration,contributions
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity
from xpu2_ray_probe import parse_rays

def bits(image):
    return b''.join(struct.pack('<%df'%len(image['channels'][c]),*image['channels'][c]) for c in 'RGBA')

def validate_profile(p,case):
    required=('submitted','collected','batches','samples','accepted','replaced','unsupported','invalid','mismatch','errors',
              'device_total_ns','initialization_ns','htod_ns','launch_ns','device_wait_ns','dtoh_ns','validation_ns',
              'diagnostic_io_ns','worker_pack_ns','queue_residence_ns','collect_ns','collect_wait_ns','cpu_light_ns','kernel_gpu_ns')
    if any(type(p.get(k)) is not int or p[k]<0 for k in required):raise ValueError('Invalid profile fields')
    if p['submitted']!=p['collected']:raise ValueError('Uncollected profile tickets')
    if case=='queue_full':
        if p['submitted'] or p['samples']:raise ValueError('Admission fallback failed')
    elif case=='missing_ptx':
        if not p['errors'] or not p['submitted'] or p['accepted'] or p['replaced']:raise ValueError('PTX fallback failed')
    else:
        if not p['samples'] or not p['submitted'] or p['accepted']!=p['samples'] or p['replaced']!=p['samples']:raise ValueError('Missing GPU validation/replacement')
        if any(p[k] for k in ('errors','mismatch','invalid','unsupported')):raise ValueError('GPU comparison failed')
        if not p['kernel_gpu_ns'] or not p['htod_ns'] or not p['dtoh_ns']:raise ValueError('Missing device timing')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('build','ptx-reference','scene-reference','output'):p.add_argument('--'+key,required=True,type=Path)
    p.add_argument('--window-dispatch',action='store_true',help='Compare timed coalescing with explicit native windows')
    a=p.parse_args();build=a.build.resolve();prior=a.scene_reference.resolve();out=a.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    report={'status':'incomplete','runs':[], 'scope':'Single-worker Lambert diagnostic; warm/uncontrolled caches, CPU reference retained; no production speedup claim',
            'timing_notes':'Wall spans may overlap across threads. Device total includes initialization and validation. Collect includes its wait. Validation includes binary-record I/O. Diagnostic I/O aggregates logging on both threads. Queue residence is summed per request, not critical-path time. GPU event interval overlaps host wait/launch. Do not sum all fields.'}
    try:
        manifest=json.loads((build/'build-inputs.json').read_text())
        if manifest['status']!='built' or not manifest.get('profile'):raise ValueError('Profiling build required')
        if a.window_dispatch and not manifest.get('window_dispatch'):raise ValueError('Window-dispatch build required')
        report['explicit_window_matrix']=a.window_dispatch
        hashes={**manifest['source_hashes'],str(Path(__file__).resolve()):digest_file(Path(__file__).resolve())}
        for name in ('images.py','native_integration.py','contributions.py'):
            path=ROOT/'xpu2'/name;hashes[str(path)]=digest_file(path)
        for path,value in hashes.items():
            if digest_file(Path(path))!=value:raise ValueError('Source drift')
        ptx=a.ptx_reference.resolve()/'sampler.ptx';ptxmeta=json.loads((a.ptx_reference/'report.json').read_text())
        if ptxmeta['status']!='passed' or digest_file(ptx)!=ptxmeta['ptx_sha256']:raise ValueError('Unverified PTX')
        reference_runtime=Path(manifest['runtime'])
        locks={str(path):inventory(path) for path in (reference_runtime,build/'control',build/'trace')}
        for label in ('control','trace'):
            for module in ('librendering_rndr.dll','librendering_shading.dll'):
                if digest_file(build/label/module)!=manifest[label+'_'+module]:raise ValueError('DLL drift')
            if digest_file(build/label/'xpu2_batched.dll')!=manifest['bridge_sha256']:raise ValueError('Bridge drift')
        reference=json.loads((prior/'report.json').read_text())
        if digest_file(prior/'scene.rdla')!=reference['diagnostic_scene_sha256']:raise ValueError('Scene drift')
        text=(prior/'scene.rdla').read_text()+'\nUsdPreviewSurface("/modo/material/1") { ["useSpecularWorkflow"]=1, ["specularColor"]=Rgb(0,0,0) }\nSceneVariables { ["shadow_terminator_fix"]=0, ["bsdf_samples"]=3 }\n'
        report.update(source_hashes=hashes,ptx_sha256=digest_file(ptx),build_manifest_sha256=digest_file(build/'build-inputs.json'),gpu=gpu_identity())
        cases=['original','control','disabled','audit_1','quiet_1','quiet_no_trace_1','quiet_no_trace_2','quiet_2','audit_2','queue_full','missing_ptx','sentinel']
        if a.window_dispatch:cases=['original','control','disabled','quiet_1','window_1','window_repeat','quiet_2','tail','serial_window','queue_full','missing_ptx','sentinel','audit_window','control_repeat','original_repeat']
        reference_image=None;reference_trace=None;reference_rays=None
        for label in cases:
            folder=out/label;folder.mkdir();runtime=reference_runtime if label.startswith('original') else build/('control' if label.startswith('control') else 'trace')
            scene=folder/'scene.rdla';scene.write_text(text,encoding='utf-8')
            env=environment(runtime,folder)
            # Never inherit diagnostic switches from the user's environment.
            for key in list(env):
                if key.startswith('XPU2_'):del env[key]
            traced=not label.startswith('quiet_no_trace')
            if traced:env.update(XPU2_TRACE_RAYS='1',XPU2_TRACE_CONTRIBUTIONS='1',XPU2_TRACE_FILE=str(folder/'trace.jsonl'))
            active=not label.startswith(('original','control','disabled'));quiet=not label.startswith('audit')
            window=a.window_dispatch and active and not label.startswith('quiet_')
            if active:
                env.update(XPU2_NATIVE_LAMBERT='sentinel' if label=='sentinel' else 'replace',XPU2_NATIVE_LAMBERT_PTX=str(folder/'missing.ptx' if label=='missing_ptx' else ptx),
                    XPU2_NATIVE_LAMBERT_LOG=str(folder/'shading.log'),XPU2_NATIVE_LAMBERT_RECORDS=str(folder/'shading.bin'),
                    XPU2_NATIVE_BATCH_WIDTH='16',XPU2_QUEUE_COALESCE_US='100',XPU2_QUEUE_POLICY='all',XPU2_QUEUE_CAPACITY='0' if label=='queue_full' else '32',
                    XPU2_QUEUE_LOG=str(folder/'queue.log'),XPU2_DEFERRED_LOG=str(folder/'deferred.log'),
                    XPU2_PROFILE_FILE=str(folder/'profile.json'),XPU2_PROFILE_QUIET='1' if quiet else '0')
                if window:env.update(XPU2_WINDOW_DISPATCH='1',XPU2_QUEUE_COALESCE_US='0',XPU2_NATIVE_BATCH_WIDTH='4' if label=='tail' else '1' if label=='serial_window' else '16')
            print('Profile '+label,flush=True);start=time.perf_counter()
            with (folder/'render.log').open('w',encoding='utf-8') as log:
                done=subprocess.run([str(runtime/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')],
                    cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
            wall=time.perf_counter()-start
            check=successful('xpu',1,done.returncode,(folder/'render.log').read_text(errors='replace'),(folder/'stats.csv').read_text() if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
            row={'label':label,'render':check,'process_wall_seconds':wall,'scene_sha256':digest_file(scene),'traced':traced,'window_dispatch':window};report['runs'].append(row)
            if not check['passed']:raise ValueError('Render failed '+label)
            image=read_rgba(runtime,folder/'beauty.exr',folder,'raw',env)
            if reference_image is None:reference_image=image
            equal=bits(reference_image)==bits(image);row['rgba_bitwise_identical']=equal
            row['image_comparison']=compare_rgba(reference_image,image)
            if label=='sentinel':
                if equal:raise ValueError('GPU sentinel did not reach film')
            elif not equal or row['image_comparison']['status']!='passed':raise ValueError('Image mismatch '+label)
            if traced:
                trace=(folder/'trace.jsonl').read_text();radiance=contributions.parse(trace);rays=parse_rays(trace)
                if not rays:raise ValueError('Missing selected rays')
                if reference_trace is None:reference_trace=radiance;reference_rays=rays
                comparison=contributions.multiset_comparison(reference_trace,radiance);shadow=contributions.shadow_changes(reference_trace,radiance)
                row.update(radiance_comparison=comparison,shadow_comparison=shadow,selected_rays_identical=rays==reference_rays)
                if label!='sentinel' and (rays!=reference_rays or shadow['visibility_changes'] or not all(r['identical_radiance_multiset'] for r in comparison)):raise ValueError('Contribution mismatch '+label)
            if active:
                profile=json.loads((folder/'profile.json').read_text());validate_profile(profile,label);row['profile']=profile
                if profile['quiet']!=quiet:raise ValueError('Incorrect profile mode')
                if not quiet:
                    counts=native_integration.summary((folder/'shading.log').read_text());observed=native_integration.records((folder/'shading.bin').read_bytes())
                    native_integration.verify_counts(counts,observed,'replace');row['shading']=counts
                    state=json.loads((folder/'deferred.log').read_text().splitlines()[-1])
                    if state['open'] or state['guard_fallback'] or state['multiple_hooks'] or state['timeouts']:raise ValueError('Native handoff failed')
                    row['deferred']=state
                elif (folder/'shading.bin').exists():raise ValueError('Quiet binary trace unexpectedly written')
            row['artifact_hashes']={f.name:digest_file(f) for f in folder.iterdir() if f.is_file() and f.suffix in ('.log','.json','.jsonl','.bin')}
            (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        normals=[r for r in report['runs'] if r['label'].startswith(('audit_','quiet_','window_','tail','serial_window'))]
        if len({r['profile']['samples'] for r in normals})!=1:raise ValueError('Profile sample count drift')
        if a.window_dispatch:
            rows={r['label']:r for r in report['runs']}
            baseline=rows['quiet_1']['profile']
            for label in ('window_1','window_repeat','audit_window'):
                profile=rows[label]['profile']
                if profile['batches']*9!=profile['submitted'] or profile['batches']>=baseline['batches']:raise ValueError('Incomplete nine-packet dispatch')
            if rows['serial_window']['profile']['batches']!=baseline['submitted']:raise ValueError('Serial window dispatch mismatch')
            if rows['tail']['profile']['batches']*3!=baseline['submitted']:raise ValueError('Four/four/one tail dispatch mismatch')
        for path,lock in locks.items():verify(Path(path),lock)
        if hashes!={p:digest_file(Path(p)) for p in hashes} or report['gpu']!=gpu_identity():raise ValueError('Source/device drift')
        report.update(status='passed',runtime_inventory_sha256={k:hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest() for k,v in locks.items()},speedup_established=False)
    except Exception as e:report['error']=str(e);raise
    finally:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
if __name__=='__main__':main()
