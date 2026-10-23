"""Private corrected-intersection comparison. Gates are fixed before rendering."""
import json,time,traceback
from pathlib import Path
from reference_runtime import sha,verify
from reference_repeatability import save,values,distance,run_reference,envelope
from run_speed_comparison import metric,quality,timing
from run_material_progressive import call
from run_m0 import guard
import asset_snapshot
HERE=Path(__file__).resolve().parent;TR=HERE.parents[1]/'test-results';OUT=TR/'interactive-ray-hit-benchmark-20261022';OUT.mkdir(exist_ok=False)
PLAN={'samples':64,'threads':[1,12],'repetitions':4,'warmup_discarded':1,'native_cpu_gpu_abs_bound':.002,'high_spp_channel':.08,'high_spp_block_mean':.015,'alpha':.015,'heldout_seeds':[17,47,101,151],'high_samples':1024,'native':'50/50 checkerboard, fine texture refill, 33 ms publication, 2 ms windows','original':'fresh pinned XPU, actual execution checked, four separate processes per thread count','timing':'native render-window wall time vs original MCRT; preparation, cold render and process wall reported separately','quality_target':'unchanged relative MSE targets and 1024-sample original images from frozen larger-scene protocol','scope':'static triangles, diffuse/emissive textured materials, direct constant environment; no production qualification'}
save(OUT/'protocol.json',PLAN);r={'status':'incomplete','production_qualified':False,'protocol':PLAN,'cases':{}}
try:
 rt=TR/'interactive-reference-042';lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);guard()
 bpath=TR/'interactive-ray-hit-shared-build-20261022/build.json';gpath=TR/'interactive-ray-hit-shared-ptx-20261022/build.json';b=json.loads(bpath.read_text());g=json.loads(gpath.read_text());decoder=json.loads((TR/'interactive-prototype-build-20261022qmc/build.json').read_text())
 assert sha(Path(b['exe']))==b['build']['executable_sha256'] and sha(Path(g['ptx']))==g['build']['ptx_sha256'] and sha(Path(decoder['exe']))==decoder['binary_hashes']['exe']
 held={**b['source_hashes'],**g['source_hashes'],str(Path(__file__).resolve()):sha(Path(__file__))};assert all(sha(Path(k))==v for k,v in held.items())
 r.update(source_hashes=held,cpu_build_sha256=sha(bpath),gpu_build_sha256=sha(gpath),runtime_identity=lock['identity'])
 checks=json.loads((TR/'interactive-ray-hit-images-shared-20261022/report.json').read_text());assert checks['status']=='measured'
 fixtures=json.loads((TR/'interactive-large-scenes-20261022/report.json').read_text());old=json.loads((TR/'interactive-large-benchmark-20261022/report.json').read_text())
 for name,fixture in fixtures['cases'].items():
  d=OUT/name;d.mkdir();w,h=fixture['resolution'];scene={int(k):Path(v) for k,v in fixture['scenes'].items()};prior=old['cases'][name];refp=Path(prior['converged_reference']['folder'])/'beauty.rgba';assert sha(refp)==prior['converged_reference']['raw_sha256'];ref=values(refp.read_bytes());target=prior['target']
  for s in scene.values():asset_snapshot.verify(s.parent/'manifest.json')
  strict={str(m):checks['cases'][name][str(m)]['max_delta'] for m in (1,2)};assert max(strict.values())<=.002
  c=r['cases'][name]={'target':target,'native':{},'original':{},'seeds':{},'ownership_max_delta':strict}
  def native(label,threads=12,repeats=4,seed=3034297317,grid=8,refill=1,publish=33,mode=2):
   dest=d/label;dest.mkdir();guard();start=time.perf_counter();row=json.loads(call([b['exe'],scene[grid],rt,g['ptx'],scene[grid].parent/'assets',dest,threads,repeats,3,seed,refill,publish,mode],rt,dest,'native',timeout=900));guard();row['wall_seconds']=time.perf_counter()-start;assert row['status']=='passed' and row['steady_gpu_synchronizations']==0
   for run in row['runs']:
    raw=Path(run['raw_file']);run['raw_sha256']=sha(raw);run['error']=metric(values(raw.read_bytes()),ref,w,h)
    assert run['cpu_committed_samples']+run['gpu_committed_samples']==w*h*grid*grid
    if refill and mode==2:assert run['gpu_committed_samples']==run['cpu_committed_samples'] and run['texture_misses_to_cpu']==run['migrated_paths']==0
   warm=row['runs'][1:] or row['runs'];row['sampling_seconds']=timing(warm,'sampling_seconds');row['meets_target']=all(v['error']['relative_mse']<=target and v['error']['alpha']<=.015 for v in row['runs']);row['repeats_identical']=len({v['raw_sha256'] for v in row['runs']})==1
   if repeats>1:assert all(v['render_allocations']==0 for v in warm)
   print(name,label,round(row['sampling_seconds']['median'],4),'target',row['meets_target'],flush=True);return row
  # Pair fresh XPU and candidate at each worker count; no simultaneous renders.
  for t in (1,12):
   orig=[]
   for i in range(4):
    _,row=run_reference(rt,scene[8],d/f'xpu-t{t}-{i}',t,Path(decoder['exe']),timeout=600);row['sampling_seconds']=row['stats']['Mcrt time (s)'];orig.append(row);print(name,'xpu',t,i,row['sampling_seconds'],flush=True)
   c['original'][str(t)]={'runs':orig,'sampling_seconds':timing(orig[1:],'sampling_seconds'),'run_to_run_abs':envelope([values((Path(v['folder'])/'beauty.rgba').read_bytes()) for v in orig])}
   save(OUT/'report.json',r);c['native'][str(t)]=native(f'candidate-t{t}',threads=t);save(OUT/'report.json',r)
  c['worker_count_byte_identical']=c['native']['1']['runs'][0]['raw_sha256']==c['native']['12']['runs'][0]['raw_sha256'];assert c['worker_count_byte_identical'] and all(v['repeats_identical'] for v in c['native'].values())
  for seed in PLAN['heldout_seeds']:
   c['seeds'][str(seed)]=native('seed-'+str(seed),repeats=1,seed=seed);save(OUT/'report.json',r)
  # Different ownership/migration and publication schedules must not change pixels.
  for label,kwargs in [('coarse-migration',{'refill':0}),('publish-every-window',{'publish':0})]:
   v=native(label,repeats=1,**kwargs);delta=distance(values(Path(v['runs'][0]['raw_file']).read_bytes()),values(Path(c['native']['12']['runs'][0]['raw_file']).read_bytes()));v['ownership_delta']=delta;assert delta<=.002;c[label]=v;save(OUT/'report.json',r)
  c['high_spp']=native('high-1024',grid=32,repeats=1);c['high_spp']['conformance_passed']=all(quality(v['error']) for v in c['high_spp']['runs']);assert c['high_spp']['conformance_passed']
  c['all_gates_passed']=all(v['meets_target'] for v in [*c['native'].values(),*c['seeds'].values()]) and c['high_spp']['conformance_passed'];assert c['all_gates_passed']
  c['warm_time_reduction_vs_xpu']={str(t):1-c['native'][str(t)]['sampling_seconds']['median']/c['original'][str(t)]['sampling_seconds']['median'] for t in (1,12)}
  for s in scene.values():asset_snapshot.verify(s.parent/'manifest.json')
  save(OUT/'report.json',r)
 assert all(sha(Path(k))==v for k,v in held.items());verify(rt,lock);guard();r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='passed')
