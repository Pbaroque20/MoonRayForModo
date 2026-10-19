"""Profile one bridge-enabled frame with unprofiled controls and exact-image checks."""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2_native_resident_probe import configuration,profiles
from xpu2_native_light_lazy_probe import competing_renderers
from xpu2_repeatability import successful,gpu_identity
from xpu2_exclusive_analyze import analyze

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for k in ('build','previous','reference','scene','ptx','light-ptx','output'):p.add_argument('--'+k,type=Path,required=True)
 a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete','runs':[]}
 def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 try:
  build=a.build.resolve();previous=a.previous.resolve();reference=a.reference.resolve();runtime=build/'runtime';oldrt=previous/'runtime'
  b=json.loads((build/'report.json').read_text());old=json.loads((previous/'report.json').read_text())
  if b['status']!='built' or old['status']!='built':raise ValueError('Unbuilt candidate')
  for rt,r in ((runtime,b),(oldrt,old)):
   if digest_file(rt/'librendering_rndr.dll')!=r['dll_sha256']:raise ValueError('Runtime drift')
  sources={**b['source_hashes'],**b['native_hashes']}
  for f in (Path(__file__),ROOT/'tools/xpu2_exclusive_analyze.py',ROOT/'tools/xpu2_native_resident_probe.py',build/'report.json',previous/'report.json',a.ptx.resolve(),a.light_ptx.resolve(),a.scene.resolve()):sources[str(f)]=digest_file(f)
  for f,h in sources.items():
   if digest_file(Path(f))!=h:raise ValueError('Source drift '+f)
  held={str(rt):inventory(rt) for rt in (runtime,oldrt,reference)};identity=gpu_identity();report.update(source_hashes=sources,gpu=identity)
  scene=out/'scene.rdla';scene.write_bytes(a.scene.read_bytes());baseline=None
  for label in ('reference','previous','unprofiled_before','profiled','unprofiled_after'):
   folder=out/label;folder.mkdir();rt=reference if label=='reference' else oldrt if label=='previous' else runtime
   env=configuration(rt,folder,a.ptx.resolve(),a.light_ptx.resolve(),'reference' if label=='reference' else 'resident')
   if label=='profiled':env.update(XPU2_EXCLUSIVE_PROFILE=str(folder/'exclusive.csv'))
   if competing_renderers():raise ValueError('Other renderer active')
   print(label,flush=True);started=time.perf_counter()
   with (folder/'render.log').open('w') as log:
    proc=subprocess.Popen([str(rt/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')],cwd=folder,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    try:proc.wait(timeout=600)
    finally:
     if proc.poll() is None:proc.kill();proc.wait(timeout=10)
   row={'label':label,'wall_seconds':time.perf_counter()-started};report['runs'].append(row);save()
   if competing_renderers():raise ValueError('Timing contaminated')
   row['execution']=successful('xpu',1,proc.returncode,(folder/'render.log').read_text(errors='replace'),(folder/'stats.csv').read_text(errors='replace') if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
   if not row['execution']['passed']:raise ValueError('Render failed '+label)
   rgba=read_rgba(rt,folder/'beauty.exr',folder,'raw',env)
   if baseline is None:baseline=rgba
   row['comparison']=compare_rgba(baseline,rgba)
   if row['comparison']['status']!='passed':raise ValueError('Instrumented image changed '+label)
   if label!='reference':row['profiles']=profiles(folder,'resident',env,require_resident_reuse=False)
   if label=='profiled':row['exclusive']=analyze(folder,row['profiles'])
   save()
  values={r['label']:r['execution']['renderer_timings_seconds']['Mcrt time'] for r in report['runs']}
  avg=(values['unprofiled_before']+values['unprofiled_after'])/2
  controls=[r for r in report['runs'] if r['label'] in ('unprofiled_before','unprofiled_after')]
  controlTrips=sum(r['profiles']['flight']['retired']+r['profiles']['light']['batches'] for r in controls)/len(controls)
  report['timing_diagnostics']={'mcrt_seconds':values,'profile_overhead_seconds_vs_bracket_mean':values['profiled']-avg,
    'profile_overhead_fraction_vs_bracket_mean':values['profiled']/avg-1,'compiled_hook_delta_vs_previous':avg-values['previous'],
    'unprofiled_bridge_gap_seconds_vs_reference':avg-values['reference'],'unprofiled_mean_gpu_trips':controlTrips,
    'additional_net_saving_us_per_trip_to_equal_reference':(avg-values['reference'])*1e6/controlTrips,
    'scope':'One profiled frame, two bracketing same-binary controls; diagnostic, not a speed qualification. Additional savings/trip is elapsed gap amortization assuming unchanged trip count, not causal attribution or total CPU replacement cost.'}
  for rt in (runtime,oldrt,reference):verify(rt,held[str(rt)])
  for f,h in sources.items():
   if digest_file(Path(f))!=h:raise ValueError('Source changed during run '+f)
  if gpu_identity()!=identity:raise ValueError('GPU identity changed')
  report['status']='passed'
 except Exception as exc:report['error']=str(exc)
 save();print(report['status'],report.get('error',''),flush=True);return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
