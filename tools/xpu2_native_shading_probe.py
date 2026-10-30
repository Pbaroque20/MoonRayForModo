"""Run actual native XPU with an isolated synchronous CUDA Lambert hook."""
import argparse
import json
import hashlib
import struct
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2 import contributions,native_integration,queue_integration
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity
from xpu2_ray_probe import parse_rays


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--build',required=True,type=Path)
    p.add_argument('--ptx-reference',required=True,type=Path)
    p.add_argument('--scene-reference',required=True,type=Path)
    p.add_argument('--output',required=True,type=Path)
    p.add_argument('--queued',action='store_true',help='Validate the worker-queue candidate, including multithread observations')
    p.add_argument('--only-multi',action='store_true',help='Run only the four-worker queue observation matrix')
    p.add_argument('--cases',help='Run an explicit subset of the diagnostic matrix (include its baseline)')
    a=p.parse_args();build,ptx_ref,prior,out=[x.resolve() for x in (a.build,a.ptx_reference,a.scene_reference,a.output)]
    if a.only_multi and not a.queued:p.error('--only-multi requires --queued')
    out.mkdir(parents=True,exist_ok=False)
    report={'status':'incomplete','scope':'Native XPU integrator with live synchronous CUDA Lambert replacement and native shadow validation; not asynchronous acceleration','runs':[]}
    try:
        manifest=json.loads((build/'build-inputs.json').read_text())
        if manifest.get('status')!='built' or bool(manifest.get('queued'))!=a.queued:raise ValueError('Incomplete shading build')
        reference=Path(manifest['runtime'])
        ptx_meta=json.loads((ptx_ref/'report.json').read_text())
        ptx=ptx_ref/'sampler.ptx'
        if ptx_meta['status']!='passed' or digest_file(ptx)!=ptx_meta['ptx_sha256']:raise ValueError('Unverified GPU shader')
        report.update(build_manifest_sha256=digest_file(build/'build-inputs.json'),ptx_sha256=digest_file(ptx),gpu_driver_identity=gpu_identity())
        locks={str(runtime):inventory(runtime) for runtime in (reference,build/'control',build/'probe')}
        for label in ('control','probe'):
            if digest_file(build/label/'librendering_shading.dll')!=manifest[label+'_dll_sha256']:raise ValueError('Shading DLL drift')
        previous=json.loads((prior/'report.json').read_text())
        if digest_file(prior/'scene.rdla')!=previous['diagnostic_scene_sha256']:raise ValueError('Reference scene drift')
        base=(prior/'scene.rdla').read_text(encoding='utf-8')
        base+='\nUsdPreviewSurface("/modo/material/1") { ["useSpecularWorkflow"]=1, ["specularColor"]=Rgb(0,0,0) }\nSceneVariables { ["shadow_terminator_fix"]=0 }\n'
        images={};traces={};rays={}
        dependencies=[Path(__file__).resolve(),ROOT/'xpu2/native_integration.py',ROOT/'xpu2/images.py',ROOT/'xpu2/contributions.py',ROOT/'xpu2'/('native_lambert_queue.cc' if a.queued else 'native_lambert_bridge.cc'),ROOT/'xpu2/queue_integration.py',ROOT/'xpu2/native_lambert_hook.ispc.inc']
        report['source_hashes']={str(f):digest_file(f) for f in dependencies}
        runs=[('original',reference,None,False),('control',build/'control',None,False),('disabled',build/'probe',None,False),
              ('audit',build/'probe','audit',False),('replace',build/'probe','replace',False),('repeat',build/'probe','replace',False),
              ('sentinel',build/'probe','sentinel',False),('missing_ptx',build/'probe','replace',False),('unsupported_control',build/'control',None,True),('unsupported',build/'probe','replace',True)]
        if a.queued:
            report['scope']='Bounded native GPU-worker queue; synchronous callers, concurrent CPU producers; not path continuations or a speed benchmark'
            runs=[('original',reference,None,False),('control',build/'control',None,False),('disabled',build/'probe',None,False),
                  ('all',build/'probe','replace',False),('mixed',build/'probe','replace',False),('mixed_repeat',build/'probe','replace',False),
                  ('sentinel',build/'probe','sentinel',False),('queue_full',build/'probe','replace',False),('missing_ptx',build/'probe','replace',False),
                  ('unsupported_control',build/'control',None,True),('unsupported',build/'probe','replace',True),
                  ('multi_control',build/'control',None,False),('multi_control_repeat',build/'control',None,False),
                  ('multi_mixed',build/'probe','replace',False),('multi_mixed_repeat',build/'probe','replace',False)]
        if a.only_multi:runs=[r for r in runs if r[0].startswith('multi_')]
        if a.cases:
            wanted=set(a.cases.split(','))
            if not wanted <= {r[0] for r in runs}:raise ValueError('Unknown diagnostic case')
            runs=[r for r in runs if r[0] in wanted]
        for label,runtime,mode,unsupported in runs:
            threads=4 if label.startswith('multi_') else 1
            folder=out/label;folder.mkdir();scene=folder/'scene.rdla'
            scene.write_text(base+('\nSceneVariables { ["shadow_terminator_fix"]=1 }\n' if unsupported else ''),encoding='utf-8')
            env=environment(runtime,folder)
            if threads==1:env.update(XPU2_TRACE_RAYS='1',XPU2_TRACE_CONTRIBUTIONS='1',XPU2_TRACE_FILE=str(folder/'trace.jsonl'))
            if mode:env.update(XPU2_NATIVE_LAMBERT=mode,XPU2_NATIVE_LAMBERT_PTX=str(folder/'missing.ptx' if label=='missing_ptx' else ptx),
                               XPU2_NATIVE_LAMBERT_LOG=str(folder/'shading.log'),XPU2_NATIVE_LAMBERT_RECORDS=str(folder/'shading.bin'))
            if a.queued and mode:
                env.update(XPU2_QUEUE_POLICY='split' if threads>1 else 'mixed' if 'mixed' in label else 'all',XPU2_QUEUE_CAPACITY='0' if label=='queue_full' else '32',XPU2_QUEUE_COALESCE_US='100' if threads>1 else '0',XPU2_QUEUE_LOG=str(folder/'queue.log'))
            command=[str(runtime/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads',str(threads),'-info','-stats',str(folder/'stats.csv')]
            print('Native XPU '+label,flush=True)
            with (folder/'render.log').open('w',encoding='utf-8') as stream:
                done=subprocess.run(command,cwd=folder,env=env,stdout=stream,stderr=subprocess.STDOUT,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
            log=(folder/'render.log').read_text(encoding='utf-8',errors='replace')
            stats=(folder/'stats.csv').read_text(encoding='utf-8',errors='replace') if (folder/'stats.csv').exists() else ''
            checks=successful('xpu',threads,done.returncode,log,stats,(folder/'beauty.exr').exists())
            row={'label':label,'render':checks,'scene_sha256':digest_file(scene)};report['runs'].append(row)
            if not checks['passed']:raise ValueError('Render failed '+label)
            images[label]=read_rgba(runtime,folder/'beauty.exr',folder,'raw',env)
            if threads==1:
                trace=(folder/'trace.jsonl').read_text(encoding='utf-8')
                traces[label]=contributions.parse(trace)
                rays[label]=parse_rays(trace)
                if not rays[label]:raise ValueError('Missing selected native surface rays')
                row['contributions']=contributions.summarize(traces[label],images[label])
            else:
                row['selected_path_tracing']='not measured: existing trace writer is single-thread-only'
            if mode and label!='queue_full':
                counts=native_integration.summary((folder/'shading.log').read_text())
                observed=native_integration.records((folder/'shading.bin').read_bytes())
                row.update(shading=counts,observations=observed)
                if label=='missing_ptx':
                    if not counts['errors'] or counts['replaced'] or counts['accepted']:raise ValueError('Missing PTX was not refused')
                else:native_integration.verify_counts(counts,observed,'unsupported' if unsupported else 'replace' if mode=='sentinel' else mode)
            if a.queued and mode:
                row['queue']=queue_integration.verify((folder/'queue.log').read_text(),None if label=='missing_ptx' else row.get('observations',{}).get('records',0),full=label=='queue_full')
            if label not in ('original','unsupported_control','multi_control'):
                baseline='unsupported_control' if unsupported else 'multi_control' if threads>1 else 'original'
                row['image_comparison']=compare_rgba(images[baseline],images[label])
                if threads==1:row['radiance_comparison']=contributions.multiset_comparison(traces[baseline],traces[label])
                if threads==1:row['shadow_comparison']=contributions.shadow_changes(traces[baseline],traces[label])
                def film_bits(image):
                    return b''.join(struct.pack('<%df' % len(image['channels'][c]),*image['channels'][c]) for c in 'RGBA')
                actual,original=film_bits(images[label]),film_bits(images[baseline])
                row['rgba_bitwise_identical']=actual==original
                row['rgba_bits_sha256']=hashlib.sha256(actual).hexdigest()
                if threads==1:row['selected_surface_rays_identical']=rays[label]==rays[baseline]
                if threads==1:row['selected_surface_ray_count']=len(rays[label])
                if label=='sentinel':
                    if actual==original or not row['image_comparison']['exactly_different_pixels'] or all(r['identical_radiance_multiset'] for r in row['radiance_comparison']):
                        raise ValueError('Sentinel did not reach native image/contributions')
                    row['expected_negative_control']=True
                elif threads>1:
                    row['image_gate']='exact' if actual==original else 'different_multithread_image'
                elif (row['image_comparison']['status']!='passed' or actual!=original or rays[label]!=rays[baseline] or
                      not all(r['identical_radiance_multiset'] for r in row['radiance_comparison']) or row['shadow_comparison']['visibility_changes']):
                    raise ValueError('Native image/contribution mismatch '+label)
            print(label+' passed '+(str(row.get('shading',{}))),flush=True)
            (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        if a.queued and all(k in images for k in ('multi_control','multi_control_repeat','multi_mixed','multi_mixed_repeat')):
            by_label={r['label']:r for r in report['runs']}
            repeated=compare_rgba(images['multi_mixed'],images['multi_mixed_repeat'])
            report['queue_gates']={
                'single_worker_image_parity':'not_run' if a.only_multi else 'passed',
                'unique_delivery_and_fallback':'passed',
                'native_four_worker_repeat':by_label['multi_control_repeat']['image_comparison'],
                'candidate_four_worker_repeat':repeated,
                'four_worker_bitwise_parity':all(by_label[k]['rgba_bitwise_identical'] for k in ('multi_control_repeat','multi_mixed','multi_mixed_repeat')),
                'cpu_gpu_overlap_observations':[{k:r['queue'][k] for k in ('cpu_completed_while_gpu_pending','kernel_window_cpu_observations','max_batch_samples')} for r in report['runs'] if r['label'] in ('multi_mixed','multi_mixed_repeat')],
                'asynchronous_path_continuations':False,
                'speedup_established':False}
        for path,lock in locks.items():verify(Path(path),lock)
        if report['gpu_driver_identity']!=gpu_identity():raise ValueError('GPU identity changed')
        if report['source_hashes']!={str(f):digest_file(f) for f in dependencies}:raise ValueError('Diagnostic source drift')
        report['runtime_inventories']=locks
        report['status']='passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
