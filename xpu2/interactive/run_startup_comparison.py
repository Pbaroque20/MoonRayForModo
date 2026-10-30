"""Private startup candidate: frozen exact images and paired warm timings."""
import json,time,subprocess,traceback,statistics
from pathlib import Path
from reference_runtime import sha,verify,identity
from reference_repeatability import save
from run_material_progressive import call
from run_m0 import guard
HERE=Path(__file__).resolve().parent;TR=HERE.parents[1]/'test-results';OUT=TR/'interactive-startup-comparison-20261022';OUT.mkdir(exist_ok=False)
protocol={'quality':'all float32 RGBA bytes identical to corrected ray-hit baseline at 1 and 12 workers','warm_speed':'candidate median <= 1.05 x paired baseline median; one warmup + three measured renders','cold_cache':'distinct empty private OptiX cache; OS file cache not purged','startup_target':'cold preparation <= .75 x baseline; cached scene preparation measured separately','threads':[1,12],'publication_ms':33,'spp':64,'reference':'unchanged pinned original XPU; prior paired reference times retained, not freshly rerendered in this startup test'}
save(OUT/'protocol.json',protocol);r={'status':'incomplete','protocol':protocol,'production_qualified':False,'cases':{}}
try:
 rt=TR/'interactive-reference-042';lock=json.loads((HERE/'reference-lock.json').read_text());guard()
 # Alternate verification modes; no GPU or scene timing runs concurrently.
 r['hash_seconds']={'1':[],'4':[]}
 for n in (1,4,4,1):
  t=time.perf_counter();verify(rt,lock,workers=n);r['hash_seconds'][str(n)].append(time.perf_counter()-t)
 # Reject altered bytes and symlink/file inventories as before; no test touches the pin.
 from tempfile import TemporaryDirectory
 from reference_runtime import inventory
 with TemporaryDirectory(dir=OUT) as temp:
  d=Path(temp);(d/'asset').write_bytes(b'original');contract={'files':inventory(d)};l={'contract':contract,'identity':identity(contract)};verify(d,l,4);(d/'asset').write_bytes(b'changed!')
  try:verify(d,l,4);raise AssertionError('Changed bytes accepted')
  except ValueError:pass
 r['changed_runtime_rejected']=True
 fixtures=json.loads((TR/'interactive-large-scenes-20261022/report.json').read_text());old=json.loads((TR/'interactive-ray-hit-benchmark-20261022/report.json').read_text())
 configs={}
 for label,bn,gn in [('baseline','interactive-startup-profile-build-20261022','interactive-ray-hit-shared-ptx-20261022'),('candidate','interactive-startup-candidate-build-20261022','interactive-startup-material-ptx-20261022')]:
  b=json.loads((TR/bn/'build.json').read_text());g=json.loads((TR/gn/'build.json').read_text());assert sha(Path(b['exe']))==b['build']['executable_sha256'] and sha(Path(g['ptx']))==g['build']['ptx_sha256'];configs[label]=(b,g)
 r['builds']={k:{'exe_sha256':sha(Path(b['exe'])),'ptx_sha256':sha(Path(g['ptx']))} for k,(b,g) in configs.items()}
 for name,f in fixtures['cases'].items():
  scene=Path(f['scenes']['8']);c=r['cases'][name]={}
  for threads in (1,12):
   c[str(threads)]={}
   for label in (('baseline','candidate') if threads==1 else ('candidate','baseline')):
    b,g=configs[label];d=OUT/(name+'-'+str(threads)+'-'+label);d.mkdir();guard();t=time.perf_counter()
    row=json.loads(call([b['exe'],scene,rt,g['ptx'],scene.parent/'assets',d,threads,4,3,3034297317,1,33,2],rt,d,'native',timeout=300));row['process_wall_seconds']=time.perf_counter()-t
    row['median_render_seconds']=statistics.median(v['sampling_seconds'] for v in row['runs'][1:]);row['median_vs_prior_xpu']=row['median_render_seconds']/old['cases'][name]['original'][str(threads)]['sampling_seconds']['median']
    expected=old['cases'][name]['native'][str(threads)]['runs'][0]['raw_sha256']
    for i,v in enumerate(row['runs']):
     v['sha256']=sha(Path(v['raw_file']));assert v['sha256']==expected,'Changed float pixels: '+name+' '+label
     assert v['cpu_committed_samples']==v['gpu_committed_samples'] and v['migrated_paths']==v['pending_paths']==0
     if i:assert v['render_allocations']==0
    assert row['steady_gpu_synchronizations']==0
    c[str(threads)][label]=row;save(OUT/'report.json',r);print(name,threads,label,'prepare',round(row['prepare_seconds'],4),'render',round(row['median_render_seconds'],4),flush=True)
   pair=c[str(threads)];pair['render_ratio']=pair['candidate']['median_render_seconds']/pair['baseline']['median_render_seconds'];pair['warm_speed_gate']=pair['render_ratio']<=1.05
  save(OUT/'report.json',r)
 r['all_warm_speed_gates']=all(v['warm_speed_gate'] for c in r['cases'].values() for v in c.values());assert r['all_warm_speed_gates'],'Warm speed regression'
 guard();verify(rt,lock);r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='passed')
