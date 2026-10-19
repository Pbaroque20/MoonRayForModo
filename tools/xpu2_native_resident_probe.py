"""Validate native GPU record-table reuse, version checks and fallback against original XPU."""
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

from xpu2_native_material_jobs_probe import configuration as jobs_configuration, profiles as jobs_profiles
from xpu2_native_material_admission_probe import require

from xpu2_native_prepared_probe import configuration as prepared_configuration, profiles as prepared_profiles

def mapped(label):
 return 'prepared' if label in ('previous','control','resident','flush','stale','lean_off') else label

def configuration(runtime,folder,ptx,light_ptx,label):
 env=prepared_configuration(runtime,folder,ptx,light_ptx,mapped(label))
 if label not in ('reference','previous'):
  env['XPU2_RESIDENT_RECORDS']='0' if label=='control' else '1'
  env['XPU2_RESIDENT_PROFILE']=str(folder/'resident.jsonl')
 if label=='flush':env['XPU2_RESIDENT_FLUSH']='1'
 if label=='stale':env['XPU2_RESIDENT_STALE']='1'
 if label=='lean_off':env['XPU2_LEAN_WIRE']='0'
 return env

def profiles(folder,label,env,bypass=False,require_cost_gpu=False,cost_cpu_only=False):
 data=prepared_profiles(folder,'mismatch' if label=='stale' else mapped(label),env,bypass)
 if label=='previous':return data
 rows=(folder/'resident.jsonl').read_text().splitlines();require(len(rows)==1,'Missing resident profile')
 p=json.loads(rows[0]);data['resident']=p
 if label=='control':require(not p['enabled'] and not p['batches'],'Resident control used GPU cache')
 else:
  require(p['enabled'],'Resident records disabled')
  if label in ('resident','flush','stale','lean_off','reuse_verify','sentinel'):
   require(p['batches']>0 and p['updates']>0 and p['descriptors']>0,'Resident path not exercised')
   if label=='flush':require(not p['reused_groups'],'Flush reused stale cache')
   elif label=='resident':require(p['reused_groups']>0,'Cross-batch record reuse absent')
  if label=='stale':require(data['gpu']['gpu_accepted']<p['descriptors']//10,'Stale references unexpectedly accepted')
  if label in ('pool0','capacity0'):require(not p['batches'],'Empty pool/capacity used cache')
 return data

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for k in ('build','previous','reference','ptx','light-ptx','scene','output'):p.add_argument('--'+k,type=Path,required=True)
 p.add_argument('--checks',action='store_true');p.add_argument('--cases')
 p.add_argument('--bypass',action='store_true');p.add_argument('--require-cost-gpu',action='store_true');p.add_argument('--cost-cpu-only',action='store_true')
 p.add_argument('--repeats',type=int,default=3)
 a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 report={'status':'incomplete','runs':[],'threads':1,'scope':'Per-flight typed/versioned GPU records for selected diffuse samples, one native worker; not scene-wide residency or broader GPU material shading.'}
 def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 try:
  require(1<=a.repeats<=5,'Invalid repeat count')
  build=a.build.resolve();previous=a.previous.resolve();runtime=build/'runtime';reference=a.reference.resolve()
  b=json.loads((build/'report.json').read_text());old=json.loads((previous/'report.json').read_text())
  require(b['status']==old['status']=='built','Build incomplete')
  require(digest_file(runtime/'librendering_rndr.dll')==b['dll_sha256'],'Candidate drift')
  require(digest_file(previous/'runtime/librendering_rndr.dll')==old['dll_sha256'],'Previous drift')
  sources={**b['source_hashes'],**b['native_hashes']}
  for path in (build/'report.json',previous/'report.json',Path(__file__).resolve(),ROOT/'tools/xpu2_native_light_lazy_probe.py',ROOT/'tools/xpu2_native_material_admission_probe.py',ROOT/'tools/xpu2_native_material_jobs_probe.py',ROOT/'tools/xpu2_native_prepared_probe.py',ROOT/'xpu2/resident_sample_cuda.cuh',ROOT/'tools/xpu2_native_resident_ptx.py',a.ptx.resolve(),a.light_ptx.resolve(),a.scene.resolve()):sources[str(path)]=digest_file(path)
  for path,h in sources.items():require(digest_file(Path(path))==h,'Source drift '+path)
  locked={str(rt):inventory(rt) for rt in (runtime,reference,previous/'runtime')};identity=gpu_identity()
  report.update(source_hashes=sources,gpu=identity,cost_cpu_only=a.cost_cpu_only,require_cost_gpu=a.require_cost_gpu,bypass=a.bypass)
  scene=out/'scene.rdla';scene.write_bytes(a.scene.read_bytes());images={};baseline=None
  allowed=('reference','previous','control','resident','flush','stale','lean_off','pool0','pool1','reuse_verify','sentinel','missing','capacity0','upload_failure','mismatch','drop')
  order=('reference','control','resident','flush') if not a.checks else allowed
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
