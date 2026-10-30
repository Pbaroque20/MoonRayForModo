"""Compare native packet grouping with the prior two-flight candidate."""
import argparse,json,os,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('build','reference','ptx','scene','output','previous'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--threads',type=int,choices=(1,4),default=1)
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--checks',action='store_true',help='Sentinel and CPU-fallback controls instead of timing repetitions')
    a=p.parse_args()
    if not 1<=a.repeats<=5:p.error('Bounded repeats/batch limit required')
    build,reference,ptx,scene,out=(getattr(a,n).resolve() for n in ('build','reference','ptx','scene','output'))
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='incomplete',threads=a.threads,runs=[],gate={'absolute':1e-6,'relative':1e-6},scope='Bounded lobe packet publication, two slots; not whole-path ownership')
    def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        m=json.loads((build/'report.json').read_text());runtime=build/'runtime';previous=a.previous.resolve()
        old=json.loads((previous/'report.json').read_text())
        if old['status']!='built' or digest_file(previous/'runtime/librendering_rndr.dll')!=old['dll_sha256']:raise ValueError('Previous runtime drift')
        if m['status']!='built' or digest_file(runtime/'librendering_rndr.dll')!=m['dll_sha256']:raise ValueError('Build drift')
        locked={str(rt):inventory(rt) for rt in (runtime,reference,previous/'runtime')}
        sources={**m['source_hashes'],**m['native_hashes']}
        for f in (ptx,scene,build/'report.json',Path(__file__),previous/'report.json'):sources[str(f)]=digest_file(f)
        for f,h in sources.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift '+f)
        report['source_hashes']=sources;gpu=gpu_identity();report['gpu']=gpu
        local=out/'scene.rdla';local.write_bytes(scene.read_bytes())
        images={};baseline=None
        labels=[(0,'reference'),(0,'disabled'),(0,'group8'),(0,'group16'),(0,'sentinel'),(0,'missing'),(0,'capacity0'),(0,'upload_failure')] if a.checks else [(0,x) for x in ('reference','legacy','ungrouped','group8','group16')]
        if not a.checks:
            base_order=('reference','legacy','ungrouped','group8','group16')
            orders=[base_order[i:]+base_order[:i] for i in range(5)]
            for n in range(a.repeats):labels.extend((n+1,x) for x in orders[n%5])
        differences=[]
        for n,label in labels:
            folder=out/(str(n)+'-'+label);folder.mkdir();rt=reference if label=='reference' else previous/'runtime' if label=='legacy' else runtime
            env=environment(rt,folder)
            for k in list(env):
                if k.startswith('XPU2_'):del env[k]
            enabled=label not in ('reference','disabled')
            slots=2
            grouped=label not in ('reference','disabled','legacy','ungrouped')
            limit=16 if label=='group16' else 8
            if enabled:
                env.update(XPU2_NATIVE_PATH_RESTORE='deferred',XPU2_NATIVE_GPU_PATHS='1',
                    XPU2_NATIVE_PATH_PROFILE=str(folder/'paths.jsonl'),XPU2_NATIVE_GPU_PROFILE=str(folder/'gpu.jsonl'),
                    XPU2_INFLIGHT_BATCHES=str(slots),XPU2_NATIVE_FLIGHT_PROFILE=str(folder/'flight.jsonl'),
                    XPU2_NATIVE_EARLY_PROFILE=str(folder/'early.jsonl'),XPU2_NATIVE_TILE_PROFILE=str(folder/'tiles.jsonl'),
                    XPU2_NATIVE_LAMBERT='execute_sentinel' if label=='sentinel' else 'execute',
                    XPU2_NATIVE_LAMBERT_PTX=str(folder/'missing.ptx' if label=='missing' else ptx),
                    XPU2_TILE_POLICY='shared',XPU2_TILE_BATCH_LIMIT=str(limit),XPU2_GROUP_PACKETS='1' if grouped else '0')
                if label=='capacity0':env['XPU2_QUEUE_CAPACITY']='0'
                if label=='upload_failure':env['XPU2_FLIGHT_FAIL_AFTER_UPLOAD']='1'
            cmd=[str(rt/'moonray.exe'),'-in',str(local),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads',str(a.threads),'-info','-stats',str(folder/'stats.csv')]
            print(n,label,flush=True);start=time.perf_counter()
            with (folder/'render.log').open('w') as log:
                run=subprocess.run(cmd,cwd=folder,env=env,stdout=log,stderr=log,timeout=600,creationflags=subprocess.CREATE_NO_WINDOW)
            seconds=time.perf_counter()-start
            check=successful('xpu',a.threads,run.returncode,(folder/'render.log').read_text(errors='replace'),(folder/'stats.csv').read_text(errors='replace') if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
            row=dict(round=n,label=label,seconds=seconds,execution=check,grouped=grouped,batch_limit=limit);report['runs'].append(row);save()
            if not check['passed']:raise ValueError('Render failed '+label)
            image=read_rgba(rt,folder/'beauty.exr',folder,'raw',env)
            if baseline is None:baseline=image
            cmp=compare_rgba(baseline,image,absolute=1e-6,relative=1e-6)
            row['comparison']=cmp
            if label=='sentinel':
                delta=compare_rgba(images['group8'],image,absolute=1e-6,relative=1e-6)
                row['sentinel_comparison']=delta
                if delta['exactly_different_pixels']<10 or max(c['maximum_absolute_error'] for c in delta['channels'].values())<1e-4:raise ValueError('GPU image sentinel failed')
            elif cmp['status']!='passed':differences.append(str(n)+'-'+label)
            images[label]=image
            if enabled:
                for key in ('paths','gpu','early','tiles','flight'):
                    data=[json.loads(x) for x in (folder/(key+'.jsonl')).read_text().splitlines()]
                    if len(data)!=1:raise ValueError('Missing teardown '+key)
                    row[key]=data[0]
                g,e,t=row['gpu'],row['early'],row['tiles']
                if g['retained'] or g['cleanup_errors'] or g['timeouts'] or e['timeouts']:raise ValueError('Lifetime failure')
                if row['paths']['captured'] or row['paths']['outstanding']:raise ValueError('Duplicate late shading')
                if g['gpu_accepted']!=e['gpu_lanes'] or g['gpu_accepted']!=g['gpu_replaced']:raise ValueError('Consumption mismatch')
                if t['claims']!=e['submitted_packets']:raise ValueError('Scheduler ownership mismatch')
                if label in ('missing','capacity0','upload_failure'):
                    if e['gpu_lanes'] or not e['fallback_lanes']:raise ValueError('Missing CPU fallback')
                    if label=='missing' and not g['gpu_errors']:raise ValueError('Missing PTX not exercised')
                elif not e['gpu_lanes'] or g['gpu_errors'] or g['gpu_mismatch']:raise ValueError('GPU not exercised')
                if t['neighbor']:raise ValueError('Wrong policy')
                f=row['flight']
                if f['slots']!=slots or f['submitted']!=f['retired'] or f['peak_inflight']>slots:raise ValueError('Flight retirement failed')
                if label=='group8' and f['peak_inflight']<2:raise ValueError('Multiple flights not exercised')
                if label=='upload_failure' and f['error_drains']!=1:raise ValueError('Upload failure did not drain')
            save()
        report['summary']={}
        for label in ('reference','legacy','ungrouped','group8','group16'):
            rows=[r for r in report['runs'] if r['round']>0 and r['label']==label]
            if rows:
                wall=[r['seconds'] for r in rows];render=[r['execution']['renderer_timings_seconds']['Mcrt time'] for r in rows]
                report['summary'][label]={'wall_median':statistics.median(wall),'wall_min':min(wall),'wall_max':max(wall),'render_median':statistics.median(render),'render_min':min(render),'render_max':max(render)}
        for rt in (reference,runtime,previous/'runtime'):verify(rt,locked[str(rt)])
        for f,h in sources.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift after test')
        if gpu_identity()!=gpu:raise ValueError('GPU identity drift')
        report['image_mismatches']=differences
        report['status']='image_differences' if differences else 'passed'
    except Exception as exc:report['error']=str(exc)
    save();print(report['status'],report.get('error',''),flush=True)
    return {'passed':0,'image_differences':2}.get(report['status'],1)
if __name__=='__main__':raise SystemExit(main())
