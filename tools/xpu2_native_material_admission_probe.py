"""Measure early material admission and remaining record/replay preparation."""
import argparse, datetime, json, os, statistics, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file, inventory, verify
from xpu2.images import read_rgba, compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful, gpu_identity
from xpu2_native_light_lazy_probe import competing_renderers

PROFILE_ENV={'paths':'NATIVE_PATH','gpu':'NATIVE_GPU','flight':'NATIVE_FLIGHT',
 'early':'NATIVE_EARLY','tiles':'NATIVE_TILE','work':'WORK','material':'MATERIAL',
 'help':'MATERIAL_HELP','context':'CONTEXT','transport':'TRANSPORT','efficiency':'EFFICIENCY',
 'cpu_ahead':'CPU_AHEAD','window':'WINDOW','coordination':'COORDINATION','owned':'OWNED',
 'packing':'VECTOR_PACK','sample_reuse':'SAMPLE_REUSE','light':'LIGHT','lazy':'LAZY',
 'claims':'TILE_CLAIM','admission':'ADMISSION'}

def configuration(runtime,folder,ptx,light_ptx,label):
 env=environment(runtime,folder)
 for k in list(env):
  if k.startswith('XPU2_'):del env[k]
 if label=='reference':return env
 env.update(XPU2_NATIVE_CHUNK_RAYS='64',XPU2_NATIVE_PATH_RESTORE='deferred',XPU2_NATIVE_GPU_PATHS='1',
  XPU2_INFLIGHT_BATCHES='2',XPU2_NATIVE_LAMBERT='execute',XPU2_NATIVE_LAMBERT_PTX=str(ptx),
  XPU2_TILE_POLICY='shared',XPU2_TILE_BATCH_LIMIT='64',XPU2_GROUP_PACKETS='1',
  XPU2_LOBE_LOOKAHEAD='1',XPU2_SHARED_INPUTS='0',XPU2_MATERIAL_STAGE='lights',
  XPU2_MATERIAL_HELP='0',XPU2_CUDA_CONTEXT='private',XPU2_BATCH_TRANSPORT='1',
  XPU2_LEAN_WIRE='1',XPU2_POLL_US='16',XPU2_CPU_LOBE_AHEAD='1',XPU2_WINDOW_BLOCKS='8',
  XPU2_QUEUE_CAPACITY='512',XPU2_OWNED_CHUNKS='4',XPU2_OWNED_MIXED='1',
  XPU2_COORDINATION='both',XPU2_NEIGHBOR_SCAN='16',XPU2_SAMPLE_REUSE='1',
  XPU2_LIGHT_GROUP='1',XPU2_LIGHT_TILES='steal',XPU2_LIGHT_LAZY='neighbor',
  XPU2_DIRECT_LIGHT='1',XPU2_LIGHT_PTX=str(light_ptx))
 mode='off' if label in ('previous','control') else 'cpu' if label=='cpu' else 'cost' if label in ('cost','profile_cost') else 'supported'
 env['XPU2_MATERIAL_ADMISSION']=mode
 for k,v in PROFILE_ENV.items():
  if label=='previous' and k=='admission':continue
  env['XPU2_'+v+'_PROFILE']=str(folder/(k+'.jsonl'))
 if label.startswith('profile_'):env['XPU2_INTEGRATION_PROFILE']=str(folder/'integration.jsonl')
 if label=='reuse_off':env['XPU2_SAMPLE_REUSE']='0'
 if label=='reuse_verify':env['XPU2_SAMPLE_REUSE']='verify'
 if label=='sentinel':env['XPU2_NATIVE_LAMBERT']='execute_sentinel'
 if label=='missing':env['XPU2_NATIVE_LAMBERT_PTX']=str(folder/'missing.ptx')
 if label=='capacity0':env['XPU2_QUEUE_CAPACITY']='0'
 if label=='upload_failure':env['XPU2_FLIGHT_FAIL_AFTER_UPLOAD']='1'
 if label=='mismatch':env['XPU2_WINDOW_MISMATCH']='1'
 if label=='drop':env['XPU2_WINDOW_DROP']='1'
 return env

def require(ok,message):
 if not ok:raise ValueError(message)

def profiles(folder,label,env,bypass=False,require_cost_gpu=False,cost_cpu_only=False):
 data={}
 for key in PROFILE_ENV:
  if label=='previous' and key=='admission':continue
  lines=(folder/(key+'.jsonl')).read_text().splitlines()
  require(len(lines)==1,'Missing frame profile '+key);data[key]=json.loads(lines[0])
 p,g,f,t,w,o,m,cp,q,l=(data[k] for k in ('paths','gpu','flight','transport','window','owned','material','cpu_ahead','light','lazy'))
 require(not p['outstanding'] and not p['captured'],'Retained native paths')
 require(not any(g[k] for k in ('timeouts','retained','cleanup_errors','gpu_mismatch')),'GPU lifetime failure')
 require(f['submitted']==f['retired'] and f['slots']==2,'Flight drain failure')
 require(not t['active'] and t['packed']==t['retired'],'Transport imbalance')
 # Packing precedes device launch. A failed launch retires a batch without a flight.
 require(t['packed']-t['failed']<=f['submitted']<=t['packed'],'Flight/packing imbalance')
 if label not in ('missing','upload_failure'):require(not t['failed'] and t['packed']==f['submitted'],'Unexpected transport failure')
 require(not w['active'] and w['published']==w['reused']+w['discarded'],'Window ownership imbalance')
 require(o['prepared']==o['finished'] and o['resumed']==o['finished'] and not o['canceled'],'Owned chunk imbalance')
 require(m['calls']==m['resumes'] and m['tokens']==m['ready_on_resume']+m['pending_on_resume'],'Material continuation imbalance')
 require(cp['packed']==cp['consumed'],'CPU lookahead imbalance')
 require(not data['early']['timeouts'],'Early timeout')
 require(data['coordination']['claimed']==data['coordination']['consumed'],'Claim imbalance')
 require(not data['packing']['mismatch'] and not data['sample_reuse']['mismatch'],'Preparation mismatch')
 require(not data['context']['retained'] and not data['help']['nested_bypass'],'Context lifetime failure')
 require(q['submitted']==q['retired']==q['collected'] and not any(q[k] for k in ('credits','abandoned','mismatch','errors','canceled')),'Light queue failure')
 require(l['windows']==l['closed'] and not l['active'] and not l['reserved'],'Light descriptors retained')
 require(l['cpu']+l['gpu']==l['descriptors'] and l['packed']==l['gpu']==q['submitted']+l['fallback'],'Light ownership imbalance')
 require(l['inspected']<=16*l['policy_claims'] and l['policy_claims']==l['descriptors'],'Unbounded light selection')
 if bypass:
  require(not g['gpu_accepted'] and not f['submitted'] and not q['submitted'],'Unsupported frame offloaded')
 elif label in ('control','previous','supported','reuse_off','reuse_verify','sentinel','profile_supported'):
  require(g['gpu_accepted']>0 and data['packing']['packets']>0,'Sampler GPU coverage absent')
 if label!='previous':
  a=data['admission'];expected={'off':0,'supported':1,'cost':2,'cpu':3}[env['XPU2_MATERIAL_ADMISSION']]
  require(a['mode']==expected,'Incorrect admission policy')
  for k in ('window','submit','lobe'):require(a[k+'_rejected']<=a[k+'_calls'],'Invalid admission counts')
  for k in ('record','replay','direct'):require(a[k+'_bytes']==a[k+'_packets']*800,'Invalid packing size')
  require(sum(a[k+'_packets'] for k in ('record','replay','direct'))==data['packing']['packets'],'Unaccounted payload preparation')
  if label=='cpu' or (cost_cpu_only and expected==2) or bypass:
   require(not data['packing']['packets'] and not g['gpu_accepted'] and not w['published'],'CPU-only policy packed sampler work')
  if require_cost_gpu and expected==2 and not bypass:require(g['gpu_accepted']>0,'Cost policy did not exercise sampler GPU')
 if label=='reuse_off':require(not data['sample_reuse']['mode'],'Reuse-off control invalid')
 if label=='reuse_verify' and not bypass:require(data['sample_reuse']['checked']>0,'Sample verification absent')
 if label=='capacity0':require(not f['submitted'] and not g['gpu_accepted'],'Capacity-zero dispatched')
 if label in ('missing','upload_failure'):require(t['failed']>0,'Injected failure absent')
 if label=='upload_failure':require(f['error_drains']==1,'Upload failure did not drain')
 if label.startswith('profile_'):data['integration']=json.loads((folder/'integration.jsonl').read_text())
 return data

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for k in ('build','previous','reference','ptx','light-ptx','scene','output'):p.add_argument('--'+k,type=Path,required=True)
 p.add_argument('--checks',action='store_true');p.add_argument('--cases')
 p.add_argument('--bypass',action='store_true');p.add_argument('--require-cost-gpu',action='store_true');p.add_argument('--cost-cpu-only',action='store_true')
 p.add_argument('--repeats',type=int,default=3)
 a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 report={'status':'incomplete','runs':[],'threads':1,'scope':'Combined pipeline with material admission before preparation; no scene loading/update claim.'}
 def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 try:
  require(1<=a.repeats<=5,'Invalid repeat count')
  build=a.build.resolve();previous=a.previous.resolve();runtime=build/'runtime';reference=a.reference.resolve()
  b=json.loads((build/'report.json').read_text());old=json.loads((previous/'report.json').read_text())
  require(b['status']==old['status']=='built','Build incomplete')
  require(digest_file(runtime/'librendering_rndr.dll')==b['dll_sha256'],'Candidate drift')
  require(digest_file(previous/'runtime/librendering_rndr.dll')==old['dll_sha256'],'Previous drift')
  sources={**b['source_hashes'],**b['native_hashes']}
  for path in (build/'report.json',previous/'report.json',Path(__file__).resolve(),ROOT/'tools/xpu2_native_light_lazy_probe.py',a.ptx.resolve(),a.light_ptx.resolve(),a.scene.resolve()):sources[str(path)]=digest_file(path)
  for path,h in sources.items():require(digest_file(Path(path))==h,'Source drift '+path)
  locked={str(rt):inventory(rt) for rt in (runtime,reference,previous/'runtime')};identity=gpu_identity()
  report.update(source_hashes=sources,gpu=identity,cost_cpu_only=a.cost_cpu_only,require_cost_gpu=a.require_cost_gpu,bypass=a.bypass)
  scene=out/'scene.rdla';scene.write_bytes(a.scene.read_bytes());images={};baseline=None
  allowed=('reference','previous','control','supported','cost','cpu','reuse_off','reuse_verify','profile_supported','profile_cost','sentinel','missing','capacity0','upload_failure','mismatch','drop')
  order=('reference','previous','control','supported','cost','cpu','reuse_off') if not a.checks else allowed
  if a.cases:
   require(a.checks,'Cases are correctness-only');order=tuple(a.cases.split(','))
   require(order and order[0]=='reference' and len(set(order))==len(order) and all(x in allowed for x in order),'Invalid cases')
  runs=[(0,label) for label in order]
  if not a.checks:
   for n in range(a.repeats):runs.extend((n+1,label) for label in order[n:]+order[:n])
  for n,label in runs:
   folder=out/(str(n)+'-'+label);folder.mkdir();rt=reference if label=='reference' else previous/'runtime' if label=='previous' else runtime
   env=configuration(rt,folder,a.ptx.resolve(),a.light_ptx.resolve(),label)
   before=competing_renderers();require(a.checks or not before,'Timing blocked by another renderer')
   print(n,label,flush=True);start=time.perf_counter();started=datetime.datetime.now(datetime.timezone.utc).isoformat()
   with (folder/'render.log').open('w') as log:
    proc=subprocess.Popen([str(rt/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')],cwd=folder,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    try:proc.wait(timeout=600)
    finally:
     if proc.poll() is None:proc.kill();proc.wait(timeout=10)
   elapsed=time.perf_counter()-start;after=competing_renderers()
   result=successful('xpu',1,proc.returncode,(folder/'render.log').read_text(errors='replace'),(folder/'stats.csv').read_text(errors='replace') if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
   row={'round':n,'label':label,'seconds':elapsed,'started_utc':started,'renderer_pid':proc.pid,'execution':result,'activity_before':before,'activity_after':after,'configuration':{k:v for k,v in env.items() if k.startswith('XPU2_')}};report['runs'].append(row);save()
   require(result['passed'],'Render failed '+label);require(a.checks or not after,'Timing contaminated')
   rgba=read_rgba(rt,folder/'beauty.exr',folder,'raw',env)
   if baseline is None:baseline=rgba
   row['comparison']=compare_rgba(baseline,rgba,absolute=1e-6,relative=1e-6);save()
   if label=='sentinel':require(row['comparison']['exactly_different_pixels']>=10,'GPU sentinel ineffective')
   else:require(row['comparison']['status']=='passed' and not row['comparison']['exactly_different_pixels'],'Image differs '+label)
   if label!='reference':row['profiles']=profiles(folder,label,env,a.bypass,a.require_cost_gpu,a.cost_cpu_only)
   images[label]=rgba;save()
  report['summary']={}
  for label in order:
   rows=[r for r in report['runs'] if r['round']>0 and r['label']==label]
   if rows:
    values=[r['execution']['renderer_timings_seconds']['Mcrt time'] for r in rows]
    report['summary'][label]={'mcrt_median':statistics.median(values),'mcrt_min':min(values),'mcrt_max':max(values),'wall_median':statistics.median(r['seconds'] for r in rows)}
  for rt in (runtime,reference,previous/'runtime'):verify(rt,locked[str(rt)])
  for path,h in sources.items():require(digest_file(Path(path))==h,'Source drift after run '+path)
  require(gpu_identity()==identity,'GPU identity drift');report['status']='passed'
 except Exception as exc:report['error']=str(exc)
 save();print(report['status'],report.get('error',''),flush=True)
 return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
