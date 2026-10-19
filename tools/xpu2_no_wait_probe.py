"""Qualify immediate CPU fallback with unprofiled controls and retained-flight recovery."""
import argparse,json,statistics,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2_native_resident_probe import configuration
from xpu2_native_light_lazy_probe import competing_renderers
from xpu2_repeatability import successful,gpu_identity

def require(value,message):
 if not value:raise ValueError(message)

def evidence(folder,enabled,frames=1,allow_errors=False):
 def rows(name):
  result=[json.loads(x) for x in (folder/(name+'.jsonl')).read_text().splitlines()]
  require(len(result)==frames,'Missing '+name+' frames');return result
 data={k:rows(k) for k in ('gpu','early','flight','material','owned','prepared','resident-detail','transport','coordination','light','lazy','window','sample_reuse')}
 nw=[json.loads(x) for x in (folder/'no-wait.jsonl').read_text().splitlines()]
 require(len(nw)==2*frames,'Missing no-wait lifecycle records');data['no_wait']=nw
 for name in ('sampler','light'):
  require(sum(x['queue']==name for x in nw)==frames,'Missing queue lifecycle')
 for x in nw:require(x['enabled']==enabled and not(x['active'] or x['pending'] or x['retained']),'Unretired no-wait queue')
 for i in range(frames):
  g,e,f,m,o,p,r,t,c,l,z,w,s=(data[k][i] for k in ('gpu','early','flight','material','owned','prepared','resident-detail','transport','coordination','light','lazy','window','sample_reuse'))
  require(not(g['retained'] or g['cleanup_errors'] or p['retained'] or r['pending'] or t['active'] or w['active']),'Retained native/record ownership')
  require(m['calls']==m['resumes'] and o['prepared']==o['finished']+o['canceled'] and o['resumed']<=o['prepared'] and c['claimed']==c['consumed'],'Native continuation imbalance')
  require(f['submitted']==f['retired'] and f['peak_inflight']<=2 and t['packed']==t['retired'],'Flight retirement imbalance')
  require(l['submitted']==l['retired']==l['collected']+l['canceled']+l['abandoned'] and not l['credits'],'Light ownership imbalance')
  require(not(z['active'] or z['reserved']) and z['windows']==z['closed'] and z['cpu']+z['gpu']==z['descriptors'],'Descriptor ownership imbalance')
  require(z['packed']==z['gpu'] and z['packed']==l['submitted']+z['fallback'],'Descriptor handoff imbalance')
  require(not(s['mismatch'] or g['gpu_mismatch'] or l['mismatch']),'Shader mismatch')
  if enabled:require(e['waits']==0 and l['waits']==0,'Rendering thread waited for GPU')
  if not allow_errors:require(not(g['gpu_errors'] or l['errors']),'Unexpected GPU error')
 return data

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for k in ('build','previous','reference','scene','ptx','light-ptx','output'):p.add_argument('--'+k,type=Path,required=True)
 p.add_argument('--mode',choices=('checks','timing','cancel'),default='checks')
 p.add_argument('--owner-stage',action='store_true',help='Qualify rolling native owner stage on the no-wait baseline')
 p.add_argument('--cases');a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 report={'status':'incomplete','mode':a.mode,'owner_stage':a.owner_stage,'threads':1,'runs':[]}
 def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 try:
  build=a.build.resolve();rt=build/'runtime';previous=a.previous.resolve();oldrt=previous/'runtime';reference=a.reference.resolve()
  b=json.loads((build/'report.json').read_text());old=json.loads((previous/'report.json').read_text())
  require(b['status']==old['status']=='built','Unbuilt runtime')
  require(digest_file(rt/'librendering_rndr.dll')==b['dll_sha256'] and digest_file(oldrt/'librendering_rndr.dll')==old['dll_sha256'],'Runtime drift')
  pinned={**b['source_hashes'],**b['native_hashes']}
  for f in (Path(__file__),ROOT/'tools/xpu2_native_resident_probe.py',build/'report.json',a.scene.resolve(),a.ptx.resolve(),a.light_ptx.resolve()):pinned[str(f)]=digest_file(f)
  for f,h in pinned.items():require(digest_file(Path(f))==h,'Source drift '+f)
  held={str(r):inventory(r) for r in (rt,oldrt,reference)};identity=gpu_identity();report.update(source_hashes=pinned,gpu=identity)
  scene=out/'scene.rdla';scene.write_bytes(a.scene.read_bytes());baseline=None;fresh=None
  order=('reference','control','no_wait','zero','held_sampler','held_light','missing','upload_failure','light_failure','stale','pool0','sentinel')
  if a.mode=='timing':order=('reference','previous','control','no_wait')
  if a.owner_stage:order=('reference','stage_off','stage_two','stage_four','zero','held_sampler','held_light','missing','upload_failure','light_failure','stale','pool0','sentinel') if a.mode=='checks' else ('reference','previous','stage_off','stage_two','stage_four')
  if a.mode=='cancel':order=('reference','fresh','restart')
  if a.cases:
   require(a.mode=='checks','Cases are correctness only');selected=tuple(a.cases.split(','));require(selected[0]=='reference' and all(x in order for x in selected),'Invalid cases');order=selected
  runs=[(0,label) for label in order]
  if a.mode=='timing':
   for n in range(3):runs.extend((n+1,label) for label in order[n:]+order[:n])
  for n,label in runs:
   folder=out/(str(n)+'-'+label);folder.mkdir();runtime=reference if label=='reference' else oldrt if label=='previous' else rt
   mapped=label if label in ('reference','missing','upload_failure','stale','pool0','sentinel') else 'resident'
   env=configuration(runtime,folder,a.ptx.resolve(),a.light_ptx.resolve(),mapped)
   enabled=label not in ('reference','previous','control','zero')
   if label!='reference':env.update(XPU2_NO_WAIT='1' if enabled else '0',XPU2_NO_WAIT_PROFILE=str(folder/'no-wait.jsonl'))
   if a.owner_stage and label!='reference':
    enabled=True;env['XPU2_NO_WAIT']='1'
    env['XPU2_OWNER_STAGE']='0' if label in ('previous','stage_off','zero') else '1'
    env['XPU2_OWNED_CHUNKS']='4' if label=='stage_four' else '2'
    env['XPU2_OWNER_STAGE_PROFILE']=str(folder/'owner-stage.jsonl')
    env['XPU2_OWNER_STAGE_HOLD_FIRST']='1' if label=='restart' else '0'
   if label in ('held_sampler','restart'):env['XPU2_NO_WAIT_HOLD_FIRST']='1'
   if label=='zero':env['XPU2_NO_WAIT_HOLD_FIRST']='0'
   if label=='held_light':env['XPU2_LIGHT_HOLD_FIRST']='1'
   if label=='light_failure':env['XPU2_LIGHT_FAIL_UPLOAD']='1'
   for key in ('XPU2_EXCLUSIVE_PROFILE','XPU2_TIMELINE','XPU2_INTEGRATION_PROFILE','XPU2_QUEUE_LOG'):env.pop(key,None)
   require(not competing_renderers(),'Competing renderer active')
   session=folder/'session';inputscene=scene
   if a.mode=='cancel':
    session.mkdir();env.update(MOONRAY_MODO_SESSION=str(session),MOONRAY_MODO_GENERATION='0')
    if label=='restart':
     inputscene=folder/'long.rdla';inputscene.write_text(scene.read_text()+'\nSceneVariables {["pixel_samples"]=16}\n')
   cmd=[str(runtime/'moonray.exe'),'-in',str(inputscene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')]
   print(n,label,flush=True);start=time.perf_counter();logpath=folder/'render.log'
   with logpath.open('w') as log:
    proc=subprocess.Popen(cmd,cwd=folder,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    try:
     if a.mode=='cancel':
      def wait(marker):
       deadline=time.monotonic()+180
       while marker not in logpath.read_text(errors='replace'):
        require(proc.poll() is None and time.monotonic()<deadline,'Missing '+marker);time.sleep(.01)
      def send(number,mode):
       tmp=session/'pending.txt';tmp.write_text('\n'.join([str(number),mode,'',str(scene)])+'\n');tmp.replace(session/'command.txt')
      if label=='restart':wait('@@XPU2_OWNER_STAGE_HELD' if a.owner_stage else '@@XPU2_NO_WAIT_HELD');send(1,'full');wait('@@MODO_SESSION CANCELED 0');wait('@@MODO_SESSION DONE 1');send(2,'quit')
      else:wait('@@MODO_SESSION DONE 0');send(1,'quit')
     proc.wait(timeout=180)
    finally:
     if proc.poll() is None:proc.kill();proc.wait(timeout=15)
   row={'round':n,'label':label,'wall_seconds':time.perf_counter()-start,'configuration':{k:v for k,v in env.items() if k.startswith('XPU2_')}};report['runs'].append(row);save()
   require(not competing_renderers(),'Timing contaminated')
   row['execution']=successful('xpu',1,proc.returncode,logpath.read_text(errors='replace'),(folder/'stats.csv').read_text(errors='replace') if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
   require(row['execution']['passed'],'Render failed '+label)
   image=read_rgba(runtime,folder/'beauty.exr',folder,'raw',env)
   if baseline is None:baseline=image
   row['comparison']=compare_rgba(baseline,image);save()
   if label=='sentinel':require(row['comparison']['exactly_different_pixels']>10,'GPU sentinel ineffective')
   else:require(row['comparison']['status']=='passed' and row['comparison']['exactly_different_pixels']==0,'Image differs '+label)
   if label not in ('reference','previous'):
    row['profiles']=evidence(folder,enabled,2 if label=='restart' else 1,label in ('missing','upload_failure','light_failure'))
    q=row['profiles']
    if label in ('no_wait','stage_two','stage_four','fresh','restart'):require(q['early'][-1]['gpu_lanes']>100,'No useful GPU work')
    if enabled:require(sum(x['late_cpu']+x['busy_refused'] for x in q['no_wait'])>0,'No opportunistic fallback')
    if label=='held_sampler':require('@@XPU2_NO_WAIT_HELD' in logpath.read_text() and next(x for x in q['no_wait'] if x['queue']=='sampler')['late_cpu']>0,'Held sampler not exercised')
    if label=='held_light':require(next(x for x in q['no_wait'] if x['queue']=='light')['late_cpu']>0,'Held light not exercised')
    if label in ('missing','upload_failure'):require(q['gpu'][-1]['gpu_errors']>0,'Sampler fault not exercised')
    if label=='light_failure':require(q['light'][-1]['errors']>0,'Light fault not exercised')
    if label=='stale':require(q['resident-detail'][-1]['rejected_records']>0,'Stale records not exercised')
    if label=='pool0':require(q['prepared'][-1]['acquired']==0 and q['prepared'][-1]['exhausted']>0,'Pool fallback not exercised')
    if label=='zero':require('@@XPU2_NO_WAIT_HELD' not in logpath.read_text() and (a.owner_stage or not any(x['busy_refused'] or x['late_cpu'] for x in q['no_wait'])),'Zero enabled policy')
    if a.owner_stage:
     stage=[json.loads(x) for x in (folder/'owner-stage.jsonl').read_text().splitlines()];q['owner_stage']=stage
     require(len(stage)==(2 if label=='restart' else 1),'Missing owner stage frames')
     if label=='restart':require(stage[0]['canceled']>0,'Cancellation missed pending owner continuations')
     else:require('@@XPU2_OWNER_STAGE_HELD' not in logpath.read_text(),'Zero owner hold flag enabled')
     stage_on=label not in ('stage_off','zero')
     for x in stage:
      require(x['enabled']==stage_on and x['produced']==x['resumed']+x['canceled'],'Unretired owner stage')
      require(x['peak_chunks']<=(4 if label=='stage_four' else 2),'Unbounded owner queue')
     if stage_on and label in ('stage_two','stage_four','fresh','restart','held_sampler','held_light'):
      require(stage[-1]['handlers']>0 and stage[-1]['produced']>0 and stage[-1]['prepared_while_queued']>0,'Owner stage not exercised')
     elif not stage_on:require(all(x['handlers']==x['produced']==0 for x in stage),'Disabled owner stage executed')
    if label=='fresh':fresh=image
    if label=='restart':
     require('@@MODO_SESSION DONE 0' not in logpath.read_text(),'Cancel too late')
     row['versus_fresh']=compare_rgba(fresh,image);require(row['versus_fresh']['exactly_different_pixels']==0,'Restart differs')
   save()
  if a.mode=='timing':
   report['summary']={}
   for label in order:
    values=[x['execution']['renderer_timings_seconds']['Mcrt time'] for x in report['runs'] if x['label']==label and x['round']>0]
    report['summary'][label]={'mcrt_median':statistics.median(values),'min':min(values),'max':max(values),'samples':values}
  for r in (rt,oldrt,reference):verify(r,held[str(r)])
  for f,h in pinned.items():require(digest_file(Path(f))==h,'Source changed during run '+f)
  require(gpu_identity()==identity,'GPU identity drift');report['status']='passed'
 except Exception as exc:report['error']=str(exc)
 save();print(report['status'],report.get('error',''),flush=True);return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
