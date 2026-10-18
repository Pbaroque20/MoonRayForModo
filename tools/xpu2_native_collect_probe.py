"""Validate bounded native cross-block prefetch, exact images and ticket lifetime."""
import argparse,datetime,json,os,re,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def competing_renderers():
    command="@(Get-CimInstance Win32_Process -Filter \"Name = 'moonray.exe'\" | Select-Object ProcessId,ExecutablePath) | ConvertTo-Json -Compress"
    result=subprocess.run(['powershell.exe','-NoProfile','-Command',command],capture_output=True,text=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:raise ValueError('Cannot verify competing render activity')
    value=json.loads(result.stdout) if result.stdout.strip() else []
    return value if isinstance(value,list) else [value]

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('build','reference','ptx','scene','output','previous'):p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--previous-ptx',type=Path,required=True)
    p.add_argument('--bypass',action='store_true',help='Require native-only fallback for an unsupported frame')
    p.add_argument('--threads',type=int,choices=(1,),default=1)
    p.add_argument('--repeats',type=int,default=3)
    p.add_argument('--cases',help='Comma-separated correctness cases; requires --checks')
    p.add_argument('--require-cpu-ahead',action='store_true')
    p.add_argument('--checks',action='store_true',help='Sentinel and CPU-fallback controls instead of timing repetitions')
    a=p.parse_args()
    if not 1<=a.repeats<=5:p.error('Bounded repeats/batch limit required')
    build,reference,ptx,scene,out=(getattr(a,n).resolve() for n in ('build','reference','ptx','scene','output'))
    out.mkdir(parents=True,exist_ok=False)
    report=dict(status='incomplete',threads=a.threads,runs=[],gate={'absolute':1e-6,'relative':1e-6},scope='64-ray chunks/eight-block windows, same-build original versus bounded 64/256us completion spin, optional inclusive integration timers; original lane packing, native math and PTX unchanged.')
    def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    try:
        m=json.loads((build/'report.json').read_text());runtime=build/'runtime';previous=a.previous.resolve()
        old=json.loads((previous/'report.json').read_text())
        if old['status']!='built' or digest_file(previous/'runtime/librendering_rndr.dll')!=old['dll_sha256']:raise ValueError('Previous runtime drift')
        if m['status']!='built' or digest_file(runtime/'librendering_rndr.dll')!=m['dll_sha256']:raise ValueError('Build drift')
        locked={str(rt):inventory(rt) for rt in (runtime,reference,previous/'runtime')}
        sources={**m['source_hashes'],**m['native_hashes']}
        for f in (ptx,scene,build/'report.json',Path(__file__),previous/'report.json',a.previous_ptx.resolve()):sources[str(f)]=digest_file(f)
        for f,h in sources.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift '+f)
        if digest_file(ptx)!=digest_file(a.previous_ptx.resolve()):raise ValueError('Changed reference shading kernel')
        report['source_hashes']=sources;gpu=gpu_identity();report['gpu']=gpu
        local=out/'scene.rdla';local.write_bytes(scene.read_bytes())
        images={};baseline=None
        order=('reference','disabled','previous','control','spin64','spin256','profile_control','profile_spin64','profile_spin256','sentinel','missing','capacity0','upload_failure','mismatch','drop') if a.checks else ('reference','previous','control','spin64','spin256')
        if a.bypass:order=('reference','disabled','spin64')
        if a.cases:
            selected=tuple(a.cases.split(','))
            if not a.checks or not selected or selected[0]!='reference' or len(set(selected))!=len(selected) or any(x not in order for x in selected):raise ValueError('Invalid control subset')
            order=selected
        labels=[(0,x) for x in order]
        if not a.checks:
            for n in range(a.repeats):labels.extend((n+1,x) for x in order[n:]+order[:n])
        differences=[]
        for n,label in labels:
            folder=out/(str(n)+'-'+label);folder.mkdir();rt=reference if label=='reference' else previous/'runtime' if label=='previous' else runtime
            env=environment(rt,folder)
            for k in list(env):
                if k.startswith('XPU2_'):del env[k]
            chunk_rays=64 if label not in ('reference','disabled') else 32
            if chunk_rays!=32:env['XPU2_NATIVE_CHUNK_RAYS']=str(chunk_rays)
            enabled=label not in ('reference','disabled','native_chunk')
            slots=2
            grouped=True
            limit=64
            if enabled:
                env.update(XPU2_NATIVE_PATH_RESTORE='deferred',XPU2_NATIVE_GPU_PATHS='1',
                    XPU2_NATIVE_PATH_PROFILE=str(folder/'paths.jsonl'),XPU2_NATIVE_GPU_PROFILE=str(folder/'gpu.jsonl'),
                    XPU2_INFLIGHT_BATCHES=str(slots),XPU2_NATIVE_FLIGHT_PROFILE=str(folder/'flight.jsonl'),
                    XPU2_NATIVE_EARLY_PROFILE=str(folder/'early.jsonl'),XPU2_NATIVE_TILE_PROFILE=str(folder/'tiles.jsonl'),
                    XPU2_NATIVE_LAMBERT='execute_sentinel' if label=='sentinel' else 'execute',
                    XPU2_NATIVE_LAMBERT_PTX=str(folder/'missing.ptx' if label=='missing' else a.previous_ptx.resolve() if label=='previous' else ptx),
                    XPU2_TILE_POLICY='shared',XPU2_TILE_BATCH_LIMIT=str(limit),XPU2_GROUP_PACKETS='1' if grouped else '0')
                env.update(XPU2_LOBE_LOOKAHEAD='1',XPU2_SHARED_INPUTS='0',XPU2_WORK_PROFILE=str(folder/'work.jsonl'),XPU2_MATERIAL_STAGE='lights',XPU2_MATERIAL_PROFILE=str(folder/'material.jsonl'),XPU2_MATERIAL_HELP='0',XPU2_MATERIAL_HELP_PROFILE=str(folder/'help.jsonl'))
                env.update(XPU2_CUDA_CONTEXT='primary' if label=='primary' else 'private',XPU2_CONTEXT_PROFILE=str(folder/'context.jsonl'))
                env.update(XPU2_BATCH_TRANSPORT='1',XPU2_TRANSPORT_PROFILE=str(folder/'transport.jsonl'))
                lean=True
                paced=True
                ahead=True
                env.update(XPU2_LEAN_WIRE='1' if lean else '0',XPU2_POLL_US='16' if paced else '0',XPU2_CPU_LOBE_AHEAD='1' if ahead else '0',XPU2_EFFICIENCY_PROFILE=str(folder/'efficiency.jsonl'),XPU2_CPU_AHEAD_PROFILE=str(folder/'cpu_ahead.jsonl'))
                width=8
                env.update(XPU2_WINDOW_BLOCKS=str(width),XPU2_WINDOW_PROFILE=str(folder/'window.jsonl'),XPU2_QUEUE_CAPACITY='512')
                pack_mode=0
                spin_us=0 if label in ('previous','control','profile_control') else 256 if label in ('spin256','profile_spin256') else 64
                if label!='previous':
                    env['XPU2_COLLECT_SPIN_US']=str(spin_us)
                    env['XPU2_COLLECT_PROFILE']=str(folder/'collect.jsonl')
                    env['XPU2_VECTOR_PACK_PROFILE']=str(folder/'packing.jsonl')
                    if pack_mode:env['XPU2_VECTOR_PACK']='1'
                    if pack_mode==2:env['XPU2_VECTOR_PACK_VERIFY']='1'
                    if label.startswith('profile_'):env['XPU2_INTEGRATION_PROFILE']=str(folder/'integration.jsonl')
                if label=='mismatch':env['XPU2_WINDOW_MISMATCH']='1'
                if label=='drop':env['XPU2_WINDOW_DROP']='1'
                if label=='capacity0':env['XPU2_QUEUE_CAPACITY']='0'
                if label=='upload_failure':env['XPU2_FLIGHT_FAIL_AFTER_UPLOAD']='1'
            cmd=[str(rt/'moonray.exe'),'-in',str(local),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads',str(a.threads),'-info','-stats',str(folder/'stats.csv')]
            activity_before=competing_renderers()
            if not a.checks and activity_before:raise ValueError('Timing blocked by competing renderer')
            print(n,label,flush=True);started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat();start=time.perf_counter()
            with (folder/'render.log').open('w') as log:
                run=subprocess.Popen(cmd,cwd=folder,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
                try:run.wait(timeout=600)
                finally:
                    if run.poll() is None:run.kill();run.wait(timeout=10)
            seconds=time.perf_counter()-start;ended_utc=datetime.datetime.now(datetime.timezone.utc).isoformat();activity_after=competing_renderers()
            check=successful('xpu',a.threads,run.returncode,(folder/'render.log').read_text(errors='replace'),(folder/'stats.csv').read_text(errors='replace') if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
            occlusion=re.search(r'GPU bundled occlusion ray utilization\s*=\s*([0-9.]+)%',(folder/'render.log').read_text(errors='replace'))
            row=dict(native_chunk_rays=chunk_rays,renderer_pid=run.pid,window_blocks=width if enabled else 0,queue_capacity=int(env['XPU2_QUEUE_CAPACITY']) if enabled else None,started_utc=started_utc,ended_utc=ended_utc,activity_before=activity_before,activity_after=activity_after,gpu_occlusion_percent=float(occlusion[1]) if occlusion else None,round=n,label=label,seconds=seconds,execution=check,grouped=grouped,batch_limit=limit);report['runs'].append(row);save()
            if not check['passed']:raise ValueError('Render failed '+label)
            image=read_rgba(rt,folder/'beauty.exr',folder,'raw',env)
            if baseline is None:baseline=image
            cmp=compare_rgba(baseline,image,absolute=1e-6,relative=1e-6)
            row['comparison']=cmp
            if label=='sentinel':
                delta=compare_rgba(images['spin64'],image,absolute=1e-6,relative=1e-6)
                row['sentinel_comparison']=delta
                if delta['exactly_different_pixels']<10 or max(c['maximum_absolute_error'] for c in delta['channels'].values())<1e-4:raise ValueError('GPU image sentinel failed')
            elif cmp['status']!='passed' or cmp['exactly_different_pixels']:differences.append(str(n)+'-'+label)
            images[label]=image
            if not a.checks and activity_after:raise ValueError('Timing contaminated by competing renderer')
            if enabled:
                for key in ('paths','gpu','early','tiles','flight','context'):
                    data=[json.loads(x) for x in (folder/(key+'.jsonl')).read_text().splitlines()]
                    if len(data)!=1:raise ValueError('Missing teardown '+key)
                    row[key]=data[0]
                ctx=row['context']
                if ctx['retained'] or ctx['retains']!=ctx['releases']:raise ValueError('Unbalanced primary context ownership')
                if label!='primary':
                    if ctx['primary'] or ctx['retains']:raise ValueError('Private control used primary context')
                elif not ctx['primary'] or ctx['retains']!=1 or ctx['active_before']!=1 or ctx['active_after']!=1:raise ValueError('Native primary context not preserved')
                w=json.loads((folder/'window.jsonl').read_text());row['window']=w
                if w['active'] or w['published']!=w['reused']+w['discarded'] or w['blocks']!=width:raise ValueError('Window ownership failure')
                if not width and w['published']:raise ValueError('Disabled window published work')
                if width and not a.bypass and label!='capacity0' and not w['published']:raise ValueError('Prefetch not exercised')
                if label in ('previous','control','spin64','spin256','profile_control','profile_spin64','profile_spin256') and not a.bypass and not w['reused']:raise ValueError('Prefetch not reused')
                if label=='mismatch' and (not w['changed'] or not w['discarded']):raise ValueError('Input mismatch not exercised')
                if label=='drop' and (not w['discarded'] or w['reused']):raise ValueError('Prefetch discard not exercised')
                g,e,t=row['gpu'],row['early'],row['tiles']
                if g['retained'] or g['cleanup_errors'] or g['timeouts'] or e['timeouts']:raise ValueError('Lifetime failure')
                if row['paths']['captured'] or row['paths']['outstanding']:raise ValueError('Duplicate late shading')
                if not 0<=g['gpu_accepted']-e['gpu_lanes']<=w['discarded']*8 or g['gpu_accepted']!=g['gpu_replaced']:raise ValueError('Consumption mismatch')
                if not 0<=e['submitted_packets']-t['claims']<=w['discarded']:raise ValueError('Scheduler ownership mismatch')
                if a.bypass:
                    if e['gpu_lanes'] or e['submitted_packets']:raise ValueError('Unsupported frame reached GPU stage')
                elif label in ('missing','capacity0','upload_failure'):
                    if e['gpu_lanes'] or not e['fallback_lanes']:raise ValueError('Missing CPU fallback')
                    if label=='missing' and not g['gpu_errors']:raise ValueError('Missing PTX not exercised')
                elif not e['gpu_lanes'] or g['gpu_errors'] or g['gpu_mismatch']:raise ValueError('GPU not exercised')
                if t['neighbor']:raise ValueError('Wrong policy')
                f=row['flight']
                if f['slots']!=slots or f['submitted']!=f['retired'] or f['peak_inflight']>slots:raise ValueError('Flight retirement failed')
                row['work']=json.loads((folder/'work.jsonl').read_text())
                row['material']=json.loads((folder/'material.jsonl').read_text())
                row['help']=json.loads((folder/'help.jsonl').read_text())
                if row['help']['calls'] or row['help']['work']:raise ValueError('Unexpected shadow helping')
                st=row['material']
                if st['calls']!=st['resumes'] or st['tokens']!=st['ready_on_resume']+st['pending_on_resume']:raise ValueError('Unbalanced material stage')
                if a.bypass and st['calls']:raise ValueError('Unsupported frame staged')
                if not a.bypass and not st['calls']:raise ValueError('Material stage not exercised')
                tr=json.loads((folder/'transport.jsonl').read_text());row['transport']=tr
                if tr['active'] or tr['packed']!=tr['retired'] or tr['bypassed']:raise ValueError('Transport ownership/identity failure')
                if not tr['enabled']:raise ValueError('Incorrect transport mode')
                if tr['packed']!=t['batches']:raise ValueError('Unaccounted transport batch')
                if not a.bypass and label!='capacity0' and not tr['packed']:raise ValueError('Transport not exercised')
                if label in ('missing','upload_failure') and not tr['failed']:raise ValueError('Transport failure not exercised')
                if label not in ('missing','upload_failure') and tr['failed']:raise ValueError('Unexpected transport failure')
                ef=json.loads((folder/'efficiency.jsonl').read_text());row['efficiency']=ef
                cp=json.loads((folder/'cpu_ahead.jsonl').read_text());row['cpu_ahead']=cp
                if cp['packed']!=cp['consumed']:raise ValueError('CPU sample reuse unbalanced')
                if not ahead and cp['packed']:raise ValueError('Unexpected CPU lookahead')
                if a.require_cpu_ahead and ahead and not a.bypass and label!='capacity0' and not cp['packed']:raise ValueError('CPU lookahead not exercised')
                if ef['lean_wire']!=lean or ef['poll_us']!=(16 if paced else 0):raise ValueError('Wrong optimization flags')
                if not lean and (ef['avoided_echo_bytes'] or ef['static_upload_bytes']):raise ValueError('Control skipped wire validation')
                if not a.bypass and label not in ('missing','capacity0','upload_failure'):
                    if lean and (not ef['avoided_echo_bytes'] or ef['static_upload_bytes']!=slots*512*4):raise ValueError('Transfer reduction absent')
                    if paced and not ef['poll_skipped']:raise ValueError('Polling not reduced')
                if label!='previous':
                    cq=json.loads((folder/'collect.jsonl').read_text());row['collect']=cq
                    if cq['spin_us']!=spin_us or cq['canceled']:raise ValueError('Collect configuration or cancellation mismatch')
                    if cq['calls']!=cq['immediate']+cq['spin_ready']+cq['slept']+cq['zero']:raise ValueError('Collect accounting mismatch')
                    if (a.bypass or not spin_us) and cq['calls']:raise ValueError('Disabled collect path executed')
                    if not a.bypass and spin_us and not cq['calls']:raise ValueError('Collect path not exercised')
                    pk=json.loads((folder/'packing.jsonl').read_text());row['packing']=pk
                    if pk['mode']!=pack_mode or pk['mismatch']:raise ValueError('Packing mode or byte mismatch')
                    if a.bypass and pk['packets']:raise ValueError('Adaptive frame packed inputs')
                    if not a.bypass and not pk['packets']:raise ValueError('Packing not exercised')
                    if pack_mode==2 and not a.bypass and (not pk['verified'] or pk['verified']!=pk['packets']):raise ValueError('Wire comparison did not cover every packet')
                    if pack_mode!=2 and pk['verified']:raise ValueError('Unexpected verification overhead')
                    if label.startswith('profile_'):
                        ip=json.loads((folder/'integration.jsonl').read_text());row['integration']=ip
                        if not a.bypass and any(not ip[k]['calls'] for k in ('window_prepare','submit_record','submit_replay','cpu_lobes','resume','collect','publish','group_record','group_replay')):raise ValueError('Missing integration phase profile')
                if label=='upload_failure' and f['error_drains']!=1:raise ValueError('Upload failure did not drain')
            save()
        report['summary']={}
        for label in order:
            rows=[r for r in report['runs'] if r['round']>0 and r['label']==label]
            if rows:
                wall=[r['seconds'] for r in rows];render=[r['execution']['renderer_timings_seconds']['Mcrt time'] for r in rows]
                report['summary'][label]={'wall_median':statistics.median(wall),'wall_min':min(wall),'wall_max':max(wall),'render_median':statistics.median(render),'render_min':min(render),'render_max':max(render)}
        for rt in (reference,runtime,previous/'runtime'):verify(rt,locked[str(rt)])
        for f,h in sources.items():
            if digest_file(Path(f))!=h:raise ValueError('Source drift after test')
        if gpu_identity()!=gpu:raise ValueError('GPU identity drift')
        report['exact_rgba_required']=True
        report['cpu_ownership']='First eligible lobe prefetched on GPU across bounded native blocks; later lobes on owning CPU worker; publication order unchanged'
        report['image_mismatches']=differences
        report['status']='image_differences' if differences else 'passed'
    except Exception as exc:report['error']=str(exc)
    save();print(report['status'],report.get('error',''),flush=True)
    return {'passed':0,'image_differences':2}.get(report['status'],1)
if __name__=='__main__':raise SystemExit(main())
