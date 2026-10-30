"""Private opt-in texture-residency and preview-cadence factorial experiment."""
import json,time,traceback
from pathlib import Path
from reference_runtime import sha,verify
from reference_repeatability import values,save,distance,run_reference
from run_speed_comparison import metric,quality,timing
from run_material_progressive import call
from run_m0 import guard
import asset_snapshot
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];TR=ROOT/'test-results'
OUT=TR/'interactive-residency-benchmark-20261022'
PLAN={'spp':64,'threads':[1,12],'repetitions':4,'discard_warmup':1,'factorial_at_12_threads':[[0,0],[1,33],[0,33],[1,0]],'refill_budget_bytes':64<<20,'trace_window_ms':2,'candidate_at_1_thread':[1,33],'high_spp':1024,'heldout_seeds':[17,47,101,151],'gates':{'native_cpu_abs':.002,'high_spp_channel':.08,'high_spp_block_mean':.015,'alpha':.015},'target':'unchanged frozen relative MSE targets from larger-scene baseline','reference_timing':'reuse same-session original medians; one fresh 12-thread control per scene reports drift separately','cold':'first render includes fine refill; preparation and cold render separate from warm median','scope':'direct diffuse/emission/constant environment; 50/50 ownership, no work donation; whole mip refill, not selective page streaming','timeout':'unchanged 120-second native frame deadline; failed cases retained'}
OUT.mkdir(exist_ok=False);save(OUT/'protocol.json',PLAN)
r={'status':'incomplete','production_qualified':False,'protocol':PLAN,'cases':{}}
try:
 rt=TR/'interactive-reference-042';lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);guard()
 sbp=TR/'interactive-residency-build-20261022/build.json';gpb=TR/'interactive-residency-ptx-20261022/build.json';oldp=TR/'interactive-large-benchmark-20261022/report.json';fp=TR/'interactive-large-scenes-20261022/report.json'
 sb=json.loads(sbp.read_text());gb=json.loads(gpb.read_text());old=json.loads(oldp.read_text());fixtures=json.loads(fp.read_text());dec=json.loads((TR/'interactive-prototype-build-20261022qmc/build.json').read_text())
 exe=Path(sb['exe']);ptx=Path(gb['ptx']);decoder=Path(dec['exe']);assert sha(exe)==sb['build']['executable_sha256'] and sha(ptx)==gb['build']['ptx_sha256'] and sha(decoder)==dec['binary_hashes']['exe']
 held={**sb['source_hashes'],**gb['source_hashes'],str(Path(__file__).resolve()):sha(Path(__file__))}
 for k,v in held.items():assert sha(Path(k))==v,'Build source drift '+k
 r.update(source_hashes=held,baseline_sha256=sha(oldp),fixtures_sha256=sha(fp),cpu_build_sha256=sha(sbp),ptx_build_sha256=sha(gpb),runtime_identity=lock['identity'])
 for name,fixture in fixtures['cases'].items():
  d=OUT/name;d.mkdir();w,h=fixture['resolution'];prior=old['cases'][name];target=prior['target'];scene={int(k):Path(v) for k,v in fixture['scenes'].items()}
  for s in scene.values():asset_snapshot.verify(s.parent/'manifest.json')
  refp=Path(prior['converged_reference']['folder'])/'beauty.rgba';assert sha(refp)==prior['converged_reference']['raw_sha256'];ref=values(refp.read_bytes())
  c=r['cases'][name]={'target':target,'original':prior['original'],'prior_native':{k:{'sampling_seconds':v.get('sampling_seconds'),'gpu_share':v['runs'][-1]['gpu_committed_samples']/(w*h*64)} for k,v in prior['native'].items()},'arms':{},'seed_checks':{}}
  def run(label,t=12,refill=1,publish=33,grid=8,repeats=4,seed=3034297317):
   dest=d/label;dest.mkdir();guard();start=time.perf_counter()
   a=[exe,scene[grid],rt,ptx,scene[grid].parent/'assets',dest,t,repeats,3,seed,refill,publish]
   result=json.loads(call(a,rt,dest,'native',timeout=900));guard();result['process_wall_seconds']=time.perf_counter()-start
   assert result['status']=='passed' and result['steady_gpu_synchronizations']==0
   for row in result['runs']:
    raw=Path(row['raw_file']);row['raw_sha256']=sha(raw);row['error']=metric(values(raw.read_bytes()),ref,w,h);row['gpu_share']=row['gpu_committed_samples']/(w*h*grid*grid)
   warm=result['runs'][1:] or result['runs'];result['sampling_seconds']=timing(warm,'sampling_seconds');result['meets_target']=all(v['error']['relative_mse']<=target and v['error']['alpha']<=.015 for v in result['runs']);result['repeats_identical']=len({v['raw_sha256'] for v in result['runs']})==1
   if repeats>1:assert all(v['render_allocations']==0 for v in result['runs'][1:]),'Warm allocation'
   if refill:assert result['active_missing_pages']==0 and all(v['migrated_paths']==0 and v['texture_misses_to_cpu']==0 and v['gpu_share']==.5 for v in result['runs']), 'Unexpected resident fallback'
   print(name,label,round(result['sampling_seconds']['median'],4),'GPU',result['runs'][-1]['gpu_share'],'target',result['meets_target'],flush=True)
   return result
  for refill,publish in PLAN['factorial_at_12_threads']:
   label=f't12-r{refill}-p{publish}'
   try:c['arms'][label]=run(label,refill=refill,publish=publish)
   except Exception as e:c['arms'][label]={'status':'failed','error':str(e),'traceback':traceback.format_exc()}
   save(OUT/'report.json',r)
  try:c['arms']['t1-r1-p33']=run('t1-r1-p33',t=1)
  except Exception as e:c['arms']['t1-r1-p33']={'status':'failed','error':str(e)}
  save(OUT/'report.json',r)
  for seed in PLAN['heldout_seeds']:
   try:c['seed_checks'][str(seed)]=run(f'seed-{seed}',seed=seed,repeats=1)
   except Exception as e:c['seed_checks'][str(seed)]={'status':'failed','error':str(e)}
   save(OUT/'report.json',r)
  try:
   c['high_spp']=run('high-1024',grid=32,repeats=1);c['high_spp']['conformance_passed']=all(quality(v['error']) for v in c['high_spp']['runs'])
  except Exception as e:c['high_spp']={'status':'failed','error':str(e),'conformance_passed':False}
  save(OUT/'report.json',r)
  im,control=run_reference(rt,scene[8],d/'fresh-xpu-12',12,decoder,timeout=600);control['relative_timing_to_prior']=control['stats']['Mcrt time (s)']/prior['original']['12']['sampling_seconds']['median'];c['fresh_reference_control']=control
  a=c['arms'];good=[v for v in a.values() if v.get('status')=='passed'];c['image_delta_between_arms']=max(distance(values(Path(v['runs'][0]['raw_file']).read_bytes()),values(Path(good[0]['runs'][0]['raw_file']).read_bytes())) for v in good)
  c['quality_passed']=c['high_spp']['conformance_passed'] and all(v.get('meets_target',False) for v in [*a.values(),*c['seed_checks'].values()])
  c['warm_savings_vs_xpu']={str(t):1-a[f't{t}-r1-p33']['sampling_seconds']['median']/prior['original'][str(t)]['sampling_seconds']['median'] for t in (1,12) if a[f't{t}-r1-p33'].get('status')=='passed'}
  c['status']='completed';save(OUT/'report.json',r)
  for s in scene.values():asset_snapshot.verify(s.parent/'manifest.json')
 assert all(sha(Path(k))==v for k,v in held.items()),'Source drift';verify(rt,lock);guard();r['status']='measured';r['all_quality_gates_passed']=all(c['quality_passed'] for c in r['cases'].values())
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True)
raise SystemExit(r['status']!='measured')
