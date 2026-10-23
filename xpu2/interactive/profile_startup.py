"""Private exclusive cold-cache and warm-cache startup measurements."""
import argparse,json,time,subprocess,os
from pathlib import Path
from run_m0 import guard
from fallback import environment
from reference_runtime import sha,verify
from reference_repeatability import save
import asset_snapshot
HERE=Path(__file__).resolve().parent;TR=HERE.parents[1]/'test-results'
p=argparse.ArgumentParser();p.add_argument('--build',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--ptx-build',type=Path,default=TR/'interactive-ray-hit-shared-ptx-20261022/build.json');a=p.parse_args()
out=a.output.resolve();out.mkdir(exist_ok=False);rt=TR/'interactive-reference-042';b=json.loads(a.build.read_text());g=json.loads(a.ptx_build.read_text());fixtures=json.loads((TR/'interactive-large-scenes-20261022/report.json').read_text())
assert sha(Path(b['exe']))==b['build']['executable_sha256']
r={'status':'incomplete','scope':'fresh processes, private empty OptiX cache followed by reused cache; OS file cache not purged','build':str(a.build.resolve()),'build_sha256':sha(a.build),'ptx_sha256':sha(Path(g['ptx'])),'cases':{}}
save(out/'protocol.json',{'startup_only':True,'cache':'private empty then reused, no global cache deletion','metrics':'exclusive CPU wall stage times; asynchronous uploads included in enqueue plus final fence, not GPU execution times'})
try:
 guard();t=time.perf_counter();verify(rt,json.loads((HERE/'reference-lock.json').read_text()));r['runtime_verify_seconds']=time.perf_counter()-t
 cache=out/'optix-cache'
 for name in ('gallery-dense','workshop-detail'):
  scene=Path(fixtures['cases'][name]['scenes']['8']);t=time.perf_counter();asset_snapshot.verify(scene.parent/'manifest.json');r['cases'][name]={'asset_verify_seconds':time.perf_counter()-t,'runs':[]}
  for i in range(2):
   guard();d=out/(name+'-'+str(i));d.mkdir();env=environment(rt,d);env['OPTIX_CACHE_PATH']=str(cache);t=time.perf_counter()
   args=[b['exe'],scene,rt,g['ptx'],scene.parent/'assets',d,12,0,3,3034297317,1,33,2,cache]
   proc=subprocess.run(list(map(str,args)),cwd=d,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240,creationflags=subprocess.CREATE_NO_WINDOW);wall=time.perf_counter()-t
   (d/'native.log').write_text(proc.stdout+proc.stderr,encoding='utf-8');assert proc.returncode==0,proc.stderr[-1600:]
   row=json.loads(proc.stdout);row['process_wall_seconds']=wall;r['cases'][name]['runs'].append(row);save(out/'report.json',r)
   print(name,i,'prepare',round(row['prepare_seconds'],3),'stages',row['startup'],flush=True)
 verify(rt,json.loads((HERE/'reference-lock.json').read_text()));guard();r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e))
save(out/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='passed')
