"""Private startup qualification: fixed gates, independent caches, paired images/timing."""
import json,subprocess,statistics,traceback,argparse,time
from pathlib import Path
from fallback import environment
from reference_runtime import sha,verify
from reference_repeatability import save
from run_m0 import guard
import asset_snapshot
HERE=Path(__file__).resolve().parent;TR=HERE.parents[1]/'test-results'
p=argparse.ArgumentParser()
for name in ('baseline-host','baseline-gpu','candidate-host','candidate-gpu','output'):p.add_argument('--'+name,type=Path,required=True)
a=p.parse_args();OUT=a.output.resolve();OUT.mkdir(exist_ok=False);rt=TR/'interactive-reference-042'
protocol={'cold_gate':'candidate module median <= 0.80 x baseline, three independently empty private caches each; OS file cache not purged','warm_gate':'candidate median <= 1.05 x baseline on both scenes at 1 and 12 workers; first render warmup, next three measured','quality_gate':'every float32 RGBA byte identical to the previous qualified corrected-ray image','scene':'unchanged frozen scenes, 64 spp, seed 3034297317, sampling policy 3, fine refill, 33ms publication','ownership':'equal CPU/GPU committed sample counts; no migrated or pending paths; no steady GPU allocations or synchronization','scope':'native preparation/render only, no Modo; original XPU not rerendered because images must equal the prior native/reference quality comparison','production_qualified':False}
save(OUT/'protocol.json',protocol);r={'status':'incomplete','protocol':protocol,'cold':{},'cases':{}}
try:
 guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()),4)
 builds={}
 for name,h,g in [('baseline',a.baseline_host,a.baseline_gpu),('candidate',a.candidate_host,a.candidate_gpu)]:
  host=json.loads(h.read_text());gpu=json.loads(g.read_text());assert sha(Path(host['exe']))==host['build']['executable_sha256'];assert sha(Path(gpu['ptx']))==gpu['binary_hashes']['ptx'];builds[name]=(host,gpu);r.setdefault('builds',{})[name]={'host':str(h.resolve()),'gpu':str(g.resolve()),'exe_sha256':sha(Path(host['exe'])),'ptx_sha256':sha(Path(gpu['ptx']))}
 fixtures=json.loads((TR/'interactive-large-scenes-20261022/report.json').read_text());old=json.loads((TR/'interactive-ray-hit-benchmark-20261022/report.json').read_text())
 def run(label,scene,threads,count,d,cache=None,mode=2):
  guard();d.mkdir();host,gpu=builds[label];env=environment(rt,d);args=[host['exe'],scene,rt,gpu['ptx'],scene.parent/'assets',d,threads,count,3,3034297317,1,33,mode]
  if cache:env['OPTIX_CACHE_PATH']=str(cache);args.append(cache)
  t=time.perf_counter();v=subprocess.run(list(map(str,args)),cwd=d,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=300,creationflags=subprocess.CREATE_NO_WINDOW);(d/'native.log').write_text(v.stdout+v.stderr,encoding='utf-8');assert not v.returncode,v.stderr[-2000:];row=json.loads(v.stdout);row['process_wall_seconds']=time.perf_counter()-t;return row
 scene=Path(fixtures['cases']['gallery-dense']['scenes']['8']);asset_snapshot.verify(scene.parent/'manifest.json')
 for rep in range(3):
  for label in (('baseline','candidate') if rep%2==0 else ('candidate','baseline')):
   d=OUT/('cold-'+str(rep)+'-'+label);row=run(label,scene,12,0,d,d/'cache');r['cold'].setdefault(label,[]).append(row);save(OUT/'report.json',r);print('cold',rep,label,'module',row['startup']['optix_module'],'prepare',row['prepare_seconds'],flush=True)
 r['cold_ratio']=statistics.median(v['startup']['optix_module'] for v in r['cold']['candidate'])/statistics.median(v['startup']['optix_module'] for v in r['cold']['baseline']);assert r['cold_ratio']<=.8,'Cold compilation gate failed'
 for name,f in fixtures['cases'].items():
  scene=Path(f['scenes']['8']);asset_snapshot.verify(scene.parent/'manifest.json');c=r['cases'][name]={}
  for threads in (1,12):
   pair=c[str(threads)]={}
   for label in (('baseline','candidate') if threads==1 else ('candidate','baseline')):
    d=OUT/(name+'-'+str(threads)+'-'+label);row=run(label,scene,threads,4,d);expected=old['cases'][name]['native'][str(threads)]['runs'][0]['raw_sha256']
    for i,v in enumerate(row['runs']):
     v['sha256']=sha(Path(v['raw_file']));assert v['sha256']==expected,'Changed float pixels: '+name+' '+label
     assert v['cpu_committed_samples']==v['gpu_committed_samples'] and v['migrated_paths']==v['pending_paths']==0
     if i:assert v['render_allocations']==0
    assert row['steady_gpu_synchronizations']==0;row['median_render_seconds']=statistics.median(v['sampling_seconds'] for v in row['runs'][1:]);pair[label]=row;save(OUT/'report.json',r);print(name,threads,label,'render',row['median_render_seconds'],'exact images',flush=True)
   pair['ratio']=pair['candidate']['median_render_seconds']/pair['baseline']['median_render_seconds'];pair['speed_gate']=pair['ratio']<=1.05
   save(OUT/'report.json',r)
 assert all(p['speed_gate'] for c in r['cases'].values() for p in c.values()),'Warm speed gate failed'
 r['ownership']={};saved=json.loads((TR/'interactive-ray-hit-images-shared-20261022/report.json').read_text())
 for name,f in fixtures['cases'].items():
  r['ownership'][name]={};scene=Path(f['scenes']['8'])
  for mode in (0,1):
   d=OUT/(name+'-ownership-'+str(mode));row=run('candidate',scene,12,1,d,mode=mode);raw=Path(row['runs'][0]['raw_file']);previous=Path(saved['cases'][name][str(mode)]['runs'][0]['raw_file']);assert raw.read_bytes()==previous.read_bytes(),'Changed ownership image';r['ownership'][name][str(mode)]={'sha256':sha(raw),'byte_identical':True,'sampling_seconds':row['runs'][0]['sampling_seconds']};save(OUT/'report.json',r);print(name,mode,'exact ownership',flush=True)
 guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()),4);r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='passed')
