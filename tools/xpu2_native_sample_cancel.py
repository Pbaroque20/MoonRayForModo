"""Validate native batch transport ownership across persistent cancellation/reload."""
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
    p.add_argument('--allow-native-roundoff',action='store_true',help='Diagnostic only: accept a baseline with native-only sub-tolerance drift; strict original-image result remains reported')
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
        diagnostic=a.allow_native_roundoff and b['status']=='image_differences'
        if diagnostic:
            native=next((r for r in b['runs'] if r['label']=='native_chunk'),None)
            if not native or native['comparison']['status']!='passed' or not native['comparison']['exactly_different_pixels']:raise ValueError('Native-only roundoff baseline required')
            if any(r['comparison']['status']!='passed' for r in b['runs'] if r['label']!='sentinel'):raise ValueError('Baseline exceeds RGB tolerance')
        if (b['status']!='passed' and not diagnostic) or b['threads']!=1 or b.get('adaptive',False):raise ValueError('Validated fixed-sample baseline required')
        report['diagnostic_native_roundoff']=diagnostic
        if b['source_hashes'][str(build/'report.json')]!=digest_file(build/'report.json'):raise ValueError('Baseline uses a different build')
        if not any(r['label']=='profile_control' and r['comparison']['status']=='passed' and r['transport']['packed']>0 for r in b['runs']):raise ValueError('GPU-shadow baseline required')
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
            if label!='reference':env.update(XPU2_TILE_POLICY='neighbor',XPU2_NEIGHBOR_SCAN='16',XPU2_NATIVE_TILE_PROFILE=str(folder/'tiles.jsonl'),XPU2_COORDINATION='both',XPU2_COORDINATION_PROFILE=str(folder/'coordination.jsonl'),XPU2_VECTOR_PACK='0',XPU2_OWNED_CHUNKS='4',XPU2_OWNED_MIXED='1',XPU2_OWNED_PROFILE=str(folder/'owned.jsonl'),XPU2_VECTOR_PACK_PROFILE=str(folder/'packing.jsonl'),XPU2_NATIVE_CHUNK_RAYS='64',XPU2_WINDOW_BLOCKS='8',XPU2_WINDOW_PROFILE=str(folder/'window.jsonl'),XPU2_QUEUE_CAPACITY='512',XPU2_LEAN_WIRE='1',XPU2_POLL_US='16',XPU2_CPU_LOBE_AHEAD='1',XPU2_EFFICIENCY_PROFILE=str(folder/'efficiency.jsonl'),XPU2_CPU_AHEAD_PROFILE=str(folder/'cpu_ahead.jsonl'),XPU2_CUDA_CONTEXT='private',XPU2_BATCH_TRANSPORT='1',XPU2_TRANSPORT_PROFILE=str(folder/'transport.jsonl'),XPU2_CONTEXT_PROFILE=str(folder/'context.jsonl'),XPU2_NATIVE_PATH_RESTORE='deferred',XPU2_NATIVE_PATH_PROFILE=str(profile),XPU2_NATIVE_PATH_POISON='1',XPU2_NATIVE_GPU_PATHS='1',XPU2_LOBE_LOOKAHEAD='1',XPU2_SHARED_INPUTS='0',XPU2_MATERIAL_STAGE='lights',XPU2_MATERIAL_HELP='0',XPU2_MATERIAL_HELP_PROFILE=str(folder/'help.jsonl'),XPU2_MATERIAL_PROFILE=str(folder/'material.jsonl'),XPU2_GROUP_PACKETS='1',XPU2_INFLIGHT_BATCHES='2',XPU2_TILE_BATCH_LIMIT='64',XPU2_NATIVE_FLIGHT_PROFILE=str(folder/'flight.jsonl'),XPU2_NATIVE_GPU_PROFILE=str(gpu_profile),XPU2_NATIVE_EARLY_PROFILE=str(early_profile),XPU2_QUEUE_LOG=str(queue_profile),XPU2_NATIVE_LAMBERT='execute',XPU2_NATIVE_LAMBERT_PTX=str(ptx),XPU2_QUEUE_COALESCE_US='1000')
            if label!='reference':env.update(XPU2_SAMPLE_REUSE='1',XPU2_SAMPLE_REUSE_PROFILE=str(folder/'sample_reuse.jsonl'))
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
                samples=[json.loads(line) for line in (folder/'sample_reuse.jsonl').read_text().splitlines()];row['sample_reuse']=samples
                if any(r['mode']!=1 or r['checked'] or r['mismatch'] for r in samples) or not samples[-1]['gpu_lanes']:raise ValueError('Sample reuse recovery failed')
                local=[json.loads(line) for line in (folder/'tiles.jsonl').read_text().splitlines()];row['tiles']=local
                if any(not t['neighbor'] or t['scan_limit']!=16 or t['inspected']>16*t['claims'] for t in local):raise ValueError('Local selection bound failed during recovery')
                cq=[json.loads(line) for line in (folder/'coordination.jsonl').read_text().splitlines()];row['coordination']=cq
                if any(not c['early'] or not c['claim'] or c['claimed']!=c['consumed'] for c in cq) or not cq[-1]['claimed']:raise ValueError('Coordination cancellation ownership failed')
                row['frames']=[json.loads(line) for line in profile.read_text().splitlines()]
                expected=[1,2] if label=='restart' else [1]
                if [e['epoch'] for e in row['frames']]!=expected:raise ValueError('Frame ownership failed')
                if any(e['captured'] or e['outstanding'] for e in row['frames']):raise ValueError('Duplicate late path dispatch')
                row['gpu']=[json.loads(line) for line in gpu_profile.read_text().splitlines()]
                row['early']=[json.loads(line) for line in early_profile.read_text().splitlines()]
                if [g['epoch'] for g in row['gpu']]!=expected or len(row['early'])!=len(expected):raise ValueError('Missing GPU epoch')
                for g,e in zip(row['gpu'],row['early']):
                    if g['retained'] or g['cleanup_errors'] or g['timeouts'] or e['timeouts'] or g['gpu_errors']:raise ValueError('GPU lifetime failed')
                row['context']=[json.loads(line) for line in (folder/'context.jsonl').read_text().splitlines()]
                if len(row['context'])!=len(expected) or any(c['primary'] or c['retained'] or c['retains'] or c['releases'] for c in row['context']):raise ValueError('Primary context lifetime failed')
                row['help']=[json.loads(line) for line in (folder/'help.jsonl').read_text().splitlines()]
                if len(row['help'])!=len(expected) or any(h['calls'] or h['work'] for h in row['help']):raise ValueError('Unexpected shadow helping')
                if any(h['nested_bypass'] for h in row['help']):raise ValueError('Shadow helping recursively entered material sampling')
                row['owned']=[json.loads(line) for line in (folder/'owned.jsonl').read_text().splitlines()]
                if len(row['owned'])!=len(expected) or any(not o['mixed'] or o['depth']!=4 or o['prepared']!=o['finished']+o['canceled'] or o['resumed']>o['prepared'] for o in row['owned']):raise ValueError('Owned chunk epoch mismatch')
                if not row['owned'][-1]['finished']:raise ValueError('Replacement did not resume owned chunks')
                row['packing']=[json.loads(line) for line in (folder/'packing.jsonl').read_text().splitlines()]
                if len(row['packing'])!=len(expected) or any(p['mode']!=0 or p['mismatch'] or p['verified'] for p in row['packing']):raise ValueError('Packing epoch state failed')
                row['window']=[json.loads(line) for line in (folder/'window.jsonl').read_text().splitlines()]
                if len(row['window'])!=len(expected) or any(w['active'] or w['published']!=w['reused']+w['discarded'] for w in row['window']):raise ValueError('Window cancellation leaked tickets')
                if not row['window'][-1]['reused']:raise ValueError('Replacement did not reuse prefetched work')
                row['material']=[json.loads(line) for line in (folder/'material.jsonl').read_text().splitlines()]
                if len(row['material'])!=len(expected) or any(m['calls']!=m['resumes'] or m['tokens']!=m['ready_on_resume']+m['pending_on_resume'] for m in row['material']):raise ValueError('Material continuation leak')
                row['cpu_ahead']=[json.loads(line) for line in (folder/'cpu_ahead.jsonl').read_text().splitlines()]
                if len(row['cpu_ahead'])!=len(expected) or any(c['packed']!=c['consumed'] for c in row['cpu_ahead']):raise ValueError('CPU lookahead lifetime failed')
                row['efficiency']=[json.loads(line) for line in (folder/'efficiency.jsonl').read_text().splitlines()]
                if len(row['efficiency'])!=len(expected) or any(not e['lean_wire'] or e['poll_us']!=16 for e in row['efficiency']):raise ValueError('Efficiency settings wrong')
                row['transport']=[json.loads(line) for line in (folder/'transport.jsonl').read_text().splitlines()]
                if len(row['transport'])!=len(expected) or any(not t['enabled'] or t['active'] or t['packed']!=t['retired'] or t['failed'] or t['bypassed'] for t in row['transport']):raise ValueError('Transport epoch ownership failed')
                if not row['transport'][-1]['packed']:raise ValueError('Replacement did not use transport')
                row['flights']=[json.loads(line) for line in (folder/'flight.jsonl').read_text().splitlines()]
                if len(row['flights'])!=len(expected) or any(f['submitted']!=f['retired'] or f['slots']!=2 for f in row['flights']):raise ValueError('Flight epoch drain failed')
                if not row['early'][-1]['gpu_lanes']:raise ValueError('Completed frame did not use GPU')
                if not 0<=row['gpu'][-1]['gpu_accepted']-row['early'][-1]['gpu_lanes']<=row['window'][-1]['discarded']*8:raise ValueError('Completed-frame consumption accounting failed')
            images[label]=read_rgba(rt,folder/'beauty.exr',folder,'image',env)
            row['comparison']=compare_rgba(images['reference'],images[label],absolute=1e-6,relative=1e-6)
            if row['comparison']['status']!='passed' or row['comparison']['exactly_different_pixels']:differences.append(label)
            if label=='restart':
                row['versus_fresh']=compare_rgba(images['fresh'],images[label],absolute=1e-6,relative=1e-6)
                if row['versus_fresh']['exactly_different_pixels']:raise ValueError('Restart not exact to fresh')
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
