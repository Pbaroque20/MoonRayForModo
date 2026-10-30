"""Private larger-scene matched-quality diagnostic using the unchanged prototype."""
import argparse,json,statistics,time,traceback
from pathlib import Path
import asset_snapshot
from reference_runtime import sha,verify
from reference_repeatability import values,run_reference,save,distance
from run_speed_comparison import metric,quality,timing
from run_material_progressive import call
from run_m0 import guard
HERE=Path(__file__).resolve().parent
PLAN={"native_sampling_policy":3,"spp":64,"reference_convergence_spp":1024,
 "threads":[1,12],"repetitions":4,"discard_warmup":1,
 "selection_seeds":[None,17,47],"heldout_seeds":[101,151],
 "target":"minimum across worker counts of median original XPU 64spp relative MSE against its 1024spp image",
 "gates":{"max_high_spp_channel_error":.08,"max_high_spp_8x8_block_bias":.015,"alpha":.015},
 "comparison":"linear float32 RGBA, no denoiser or display transform; high-spp check is one native seed",
 "scope":"same 2ms progressive renderWindows; synthetic flat-triangle diffuse/emission/constant-environment subset",
 "limits":"native 120-second render watchdog unchanged; no production qualification; reference repeatability remains open",
 "cache":"native repeats retain scene, textures and workers; original is fresh process with warm OS/OptiX disk caches; preparation reported separately",
 "failure_policy":"preserve failed gates and failures; never relax thresholds; fixed 64spp comparison, no sample-budget search"}

def main():
 p=argparse.ArgumentParser()
 for n in ('runtime','build','speed-build','fixtures','output'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--diagnostic',action='store_true')
 a=p.parse_args();out=a.output.resolve();out.mkdir(exist_ok=False);save(out/'protocol.json',PLAN)
 r={'status':'incomplete','production_qualified':False,'protocol':PLAN,'cases':{}}
 try:
  assert a.diagnostic,'Unqualified reference requires diagnostic opt-in'
  rt=a.runtime.resolve();lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);guard()
  b=json.loads(a.build.read_text());s=json.loads(a.speed_build.read_text());f=json.loads(a.fixtures.read_text());assert b['status']==s['status']=='passed' and f['status']=='prepared'
  bench=Path(s['exe']);decoder=Path(b['exe']);ptx=Path(b['ptx'])
  assert sha(bench)==s['build']['executable_sha256'] and sha(decoder)==b['binary_hashes']['exe'] and sha(ptx)==b['binary_hashes']['ptx']
  held={**s['source_hashes'],**{str(HERE/n):sha(HERE/n) for n in ('run_large_sampling.py','run_speed_comparison.py','reference_repeatability.py','asset_snapshot.py')}}
  for k,v in held.items():assert sha(Path(k))==v,'CPU source drift '+k
  for n in ('gpu_trace.cu','gpu_jobs.h','texture_core.h','resume_core.h','surface_core.h','sample_stream.h','path_stage.h'):assert sha(HERE/n)==b['source_hashes'][str(HERE/n)],'GPU source drift'
  r.update(reference_identity=lock['identity'],source_hashes=held,fixtures_sha256=sha(a.fixtures),build_sha256=sha(a.build),speed_build_sha256=sha(a.speed_build))
  for name,fixture in f['cases'].items():
   folder=out/name;folder.mkdir();w,h=fixture['resolution'];case=r['cases'][name]={'fixture':fixture,'original':{},'native':{},'seed_checks':{},'high_spp':{}}
   scenes={int(k):Path(v) for k,v in fixture['scenes'].items()}
   for v in scenes.values():asset_snapshot.verify(v.parent/'manifest.json')
   def native(label,grid=8,t=12,repeats=1,seed=None):
    d=folder/label;d.mkdir();scene=scenes[grid];args=[bench,scene,rt,ptx,scene.parent/'assets',d,t,repeats,3]
    if seed is not None:args.append(seed)
    guard();start=time.perf_counter();data=json.loads(call(args,rt,d,'native',timeout=900));data['process_wall_seconds']=time.perf_counter()-start;guard()
    assert data['status']=='passed' and data['workers_created']==t and data['steady_gpu_allocations']==data['steady_gpu_synchronizations']==0
    for row in data['runs']:
     raw=Path(row['raw_file']);row['raw_sha256']=sha(raw)
    data['sampling_seconds']=timing(data['runs'][1:] or data['runs'],'sampling_seconds')
    data['first_partial_seconds']=timing(data['runs'][1:] or data['runs'],'first_partial_seconds')
    print(name,label,'seconds',round(data['sampling_seconds']['median'],4),'gpu share',round(data['runs'][-1]['gpu_committed_samples']/(w*h*grid*grid),4),flush=True)
    return data
   # Admission pilot is also the native warm-up and measured same-spp 12-worker set.
   try:
    case['native']['12']=native('native-t12',repeats=4);save(out/'report.json',r)
   except Exception as e:
    case.update(status='native-failed',error=str(e),traceback=traceback.format_exc());save(out/'report.json',r);continue
   ref,meta=run_reference(rt,scenes[32],folder/'reference-1024',12,decoder,timeout=1200);case['converged_reference']=meta;print(name,'reference 1024 spp',meta['stats'],flush=True);save(out/'report.json',r)
   # All reference results freeze the target before alternate native seeds are viewed.
   for t in PLAN['threads']:
    rows=case['original'][str(t)]={'runs':[]};pixels=[]
    for i in range(4):
     im,row=run_reference(rt,scenes[8],folder/f'xpu-t{t}-{i}',t,decoder,timeout=600);row['error']=metric(im,ref,w,h);rows['runs'].append(row);pixels.append(im)
     print(name,'XPU',t,i,round(row['stats']['Mcrt time (s)'],4),flush=True);save(out/'report.json',r)
    rows['sampling_seconds']=timing([v['stats'] for v in rows['runs'][1:]],'Mcrt time (s)');rows['prepare_seconds']=timing([v['stats'] for v in rows['runs'][1:]],'Render prep (s)')
    rows['repeat_max_channel_delta']=max(distance(im,pixels[0]) for im in pixels);rows['target']=statistics.median(v['error']['relative_mse'] for v in rows['runs'][1:])
   case['target']=min(v['target'] for v in case['original'].values());save(folder/'frozen-target.json',{'target':case['target'],'protocol':PLAN,'reference':case['original']})
   def assess(data):
    for row in data['runs']:row['error']=metric(values(Path(row['raw_file']).read_bytes()),ref,w,h)
    data['meets_target']=all(v['error']['relative_mse']<=case['target'] and v['error']['alpha']<=.015 for v in data['runs'])
    return data
   assess(case['native']['12']);save(out/'report.json',r)
   case['native']['1']=assess(native('native-t1',t=1,repeats=4));save(out/'report.json',r)
   for seed in (17,47,101,151):
    case['seed_checks'][str(seed)]=assess(native(f'seed-{seed}',seed=seed));save(out/'report.json',r)
   try:
    case['high_spp']=assess(native('native-1024',grid=32));case['high_spp']['conformance_passed']=all(quality(v['error']) for v in case['high_spp']['runs'])
   except Exception as e:case['high_spp']={'status':'failed','error':str(e),'conformance_passed':False}
   case['native_repeat_identical']=all(len(set(v['raw_sha256'] for v in data['runs']))==1 for data in case['native'].values())
   case['native_worker_counts_identical']=case['native']['1']['runs'][0]['raw_sha256']==case['native']['12']['runs'][0]['raw_sha256']
   case['quality_passed']=case['high_spp']['conformance_passed'] and all(v['meets_target'] for v in list(case['native'].values())+list(case['seed_checks'].values()))
   case['render_phase_savings']={str(t):1-case['native'][str(t)]['sampling_seconds']['median']/case['original'][str(t)]['sampling_seconds']['median'] for t in PLAN['threads']}
   case['status']='completed';save(out/'report.json',r)
   for v in scenes.values():asset_snapshot.verify(v.parent/'manifest.json')
  assert all(sha(Path(k))==v for k,v in held.items()),'Source drift during run';verify(rt,lock);guard()
  r.update(status='partial',measurement_status='completed',reason='Diagnostic subset; finite reference-repeatability qualification remains open')
 except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
 save(out/'report.json',r);print(r['status'],r.get('error',''),flush=True);return int(r.get('measurement_status')!='completed')
if __name__=='__main__':raise SystemExit(main())
