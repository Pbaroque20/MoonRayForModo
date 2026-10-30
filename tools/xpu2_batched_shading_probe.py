"""Native render checks for a batched Lambert result with a resident CPU stack."""
import argparse,hashlib,json,struct,subprocess,sys
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

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('build','ptx-reference','scene-reference','output'):p.add_argument('--'+key,required=True,type=Path)
    a=p.parse_args();build=a.build.resolve();prior=a.scene_reference.resolve();out=a.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    report={'status':'incomplete','scope':'Native bounded window of GPU submits and CPU light evaluations, then ordered collection; CPU reference shading and resident stack retained','runs':[]}
    try:
        manifest=json.loads((build/'build-inputs.json').read_text())
        if manifest['status']!='built':raise ValueError('Incomplete build')
        hashes={**manifest['source_hashes'],str(Path(__file__).resolve()):digest_file(Path(__file__).resolve())}
        for name in ('images.py','native_integration.py','contributions.py'):
            path=ROOT/'xpu2'/name;hashes[str(path)]=digest_file(path)
        for path,value in hashes.items():
            if digest_file(Path(path))!=value:raise ValueError('Source drift')
        ptx=a.ptx_reference.resolve()/'sampler.ptx';ptx_meta=json.loads((a.ptx_reference/'report.json').read_text())
        if ptx_meta['status']!='passed' or digest_file(ptx)!=ptx_meta['ptx_sha256']:raise ValueError('Unverified PTX')
        reference_runtime=Path(manifest['runtime'])
        locks={str(path):inventory(path) for path in (reference_runtime,build/'control',build/'trace')}
        for label in ('control','trace'):
            for module in ('librendering_rndr.dll','librendering_shading.dll'):
                if digest_file(build/label/module)!=manifest[label+'_'+module]:raise ValueError('DLL drift')
            if digest_file(build/label/'xpu2_batched.dll')!=manifest['bridge_sha256']:raise ValueError('Bridge drift')
        reference=json.loads((prior/'report.json').read_text())
        if digest_file(prior/'scene.rdla')!=reference['diagnostic_scene_sha256']:raise ValueError('Scene drift')
        text=(prior/'scene.rdla').read_text()+'\nUsdPreviewSurface("/modo/material/1") { ["useSpecularWorkflow"]=1, ["specularColor"]=Rgb(0,0,0) }\nSceneVariables { ["shadow_terminator_fix"]=0 }\n'
        report.update(source_hashes=hashes,ptx_sha256=digest_file(ptx),build_manifest_sha256=digest_file(build/'build-inputs.json'),gpu=gpu_identity())
        images={};traces={};rays={}
        cases=[('original',False,None),('control',False,None),('disabled',True,None),('replace',True,'replace'),('repeat',True,'replace'),
               ('serial_window',True,'replace'),('sentinel',True,'sentinel'),('queue_full',True,'replace'),('missing_ptx',True,'replace'),
               ('unsupported_control',False,None),('unsupported',True,'replace')]
        for label,probe,mode in cases:
            runtime=reference_runtime if label=='original' else build/('trace' if probe else 'control');folder=out/label;folder.mkdir()
            unsupported=label.startswith('unsupported');scene=folder/'scene.rdla'
            scene.write_text(text+('\nSceneVariables { ["shadow_terminator_fix"]=1 }\n' if unsupported else ''),encoding='utf-8')
            env=environment(runtime,folder)
            env.update(XPU2_TRACE_RAYS='1',XPU2_TRACE_CONTRIBUTIONS='1',XPU2_TRACE_FILE=str(folder/'trace.jsonl'))
            for name in ('XPU2_NATIVE_LAMBERT','XPU2_DEFERRED_LOG','XPU2_QUEUE_LOG'):env.pop(name,None)
            if mode:
                env.update(XPU2_NATIVE_LAMBERT=mode,XPU2_NATIVE_LAMBERT_PTX=str(folder/'missing.ptx' if label=='missing_ptx' else ptx),
                    XPU2_NATIVE_LAMBERT_LOG=str(folder/'shading.log'),XPU2_NATIVE_LAMBERT_RECORDS=str(folder/'shading.bin'),
                    XPU2_NATIVE_BATCH_WIDTH='1' if label=='serial_window' else '4',XPU2_QUEUE_COALESCE_US='100',
                    XPU2_QUEUE_POLICY='all',XPU2_QUEUE_CAPACITY='0' if label=='queue_full' else '32',
                    XPU2_QUEUE_LOG=str(folder/'queue.log'),XPU2_DEFERRED_LOG=str(folder/'deferred.log'))
            print('Native batched '+label,flush=True)
            with (folder/'render.log').open('w',encoding='utf-8') as log:
                done=subprocess.run([str(runtime/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')],
                    cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
            check=successful('xpu',1,done.returncode,(folder/'render.log').read_text(errors='replace'),(folder/'stats.csv').read_text() if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
            row={'label':label,'render':check,'scene_sha256':digest_file(scene)};report['runs'].append(row)
            if not check['passed']:raise ValueError('Render failed '+label)
            images[label]=read_rgba(runtime,folder/'beauty.exr',folder,'raw',env)
            trace=(folder/'trace.jsonl').read_text()
            traces[label]=contributions.parse(trace);rays[label]=parse_rays(trace)
            if not rays[label]:raise ValueError('Missing rays')
            if mode:
                records=[json.loads(line) for line in (folder/'deferred.log').read_text().splitlines()]
                state=records[-1];row['deferred']=state
                if state['open'] or state['peak_open']>4 or state['guard_fallback'] or state['multiple_hooks'] or state['timeouts'] or state['submitted']!=state['collected']:raise ValueError('Deferred native handoff failed')
                rows=[json.loads(line) for line in (folder/'queue.log').read_text().splitlines() if line.startswith('{')]
                q=[v for v in rows if 'calls' in v][-1];ids=[v['delivered_id'] for v in rows if 'delivered_id' in v]
                row['queue']=q
                if q['retained_async'] or q['worker_failures'] or q['submitted']!=q['delivered'] or q['delivered']!=state['collected'] or len(ids)!=len(set(ids)) or len(ids)!=q['delivered']:raise ValueError('Unbalanced queue')
                if q['calls']!=q['submitted']+q['queue_full']:raise ValueError('Unaccounted queue calls')
                if label=='queue_full':
                    if not q['queue_full'] or q['submitted'] or (folder/'shading.log').exists():raise ValueError('Admission fallback failed')
                else:
                    counts=native_integration.summary((folder/'shading.log').read_text());observed=native_integration.records((folder/'shading.bin').read_bytes())
                    row.update(shading=counts,observations=observed)
                    if label=='missing_ptx':
                        if not counts['errors'] or counts['accepted'] or counts['replaced'] or observed['records']:raise ValueError('Missing-PTX fallback failed')
                    else:native_integration.verify_counts(counts,observed,'unsupported' if unsupported else 'replace')
                    if not state['light_calls'] or not state['collected']:raise ValueError('No native CPU light work before collect')
            baseline='unsupported_control' if unsupported else 'original'
            if label!=baseline:
                comparison=compare_rgba(images[baseline],images[label]);equal=bits(images[baseline])==bits(images[label])
                radiance=contributions.multiset_comparison(traces[baseline],traces[label]);shadow=contributions.shadow_changes(traces[baseline],traces[label])
                row.update(image_comparison=comparison,rgba_bitwise_identical=equal,radiance_comparison=radiance,shadow_comparison=shadow,selected_rays_identical=rays[baseline]==rays[label])
                if label=='sentinel':
                    if equal or all(r['identical_radiance_multiset'] for r in radiance):raise ValueError('Deferred GPU answer did not reach film')
                    row['expected_negative_control']=True
                elif not equal or comparison['status']!='passed' or not row['selected_rays_identical'] or not all(r['identical_radiance_multiset'] for r in radiance) or shadow['visibility_changes']:raise ValueError('Native contribution/image mismatch')
            row['log_hashes']={f.name:digest_file(f) for f in folder.iterdir() if f.is_file() and f.suffix in ('.log','.jsonl','.bin')}
            (out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        for path,lock in locks.items():verify(Path(path),lock)
        if hashes!={p:digest_file(Path(p)) for p in hashes} or report['gpu']!=gpu_identity():raise ValueError('Source/device drift')
        by_label={r['label']:r for r in report['runs']}
        batch=by_label['replace']['queue'];serial=by_label['serial_window']['queue']
        if batch['max_batch_samples']<=8 or batch['worker_batches']>=serial['worker_batches']:raise ValueError('Native batching did not reduce GPU dispatches')
        report['batch_comparison']={'serial_worker_batches':serial['worker_batches'],'batched_worker_batches':batch['worker_batches'],
            'max_batch_samples':batch['max_batch_samples'],'kernel_overlap_observations':batch['kernel_window_cpu_observations'],
            'timings_are_instrumented_not_a_benchmark':True}
        report.update(status='passed',runtime_inventory_sha256={k:hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':')).encode()).hexdigest() for k,v in locks.items()},
                      native_whole_path_suspension=False,speedup_established=False)
    except Exception as e:report['error']=str(e);raise
    finally:(out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
