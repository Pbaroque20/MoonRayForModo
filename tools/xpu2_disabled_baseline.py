"""Measure a genuinely disabled XPU2 build against original XPU at 1 and all CPU threads.
No experimental GPU flags are enabled. Multiworker image differences are reported,
not silently accepted as parity. This is a baseline, not multiworker XPU2 validation.
"""
import argparse, datetime, json, os, statistics, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file, inventory, verify
from xpu2.images import read_rgba, compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful, gpu_identity
from xpu2_native_light_lazy_probe import competing_renderers


def main():
 p=argparse.ArgumentParser(description=__doc__)
 for k in ('build','reference','scene','output'):p.add_argument('--'+k,type=Path,required=True)
 p.add_argument('--threads',type=int,default=os.cpu_count())
 p.add_argument('--repeats',type=int,default=3)
 a=p.parse_args()
 if not 2<=a.threads<=256 or not 3<=a.repeats<=10:p.error('Need 2..256 threads and 3..10 repetitions')
 out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 report=dict(status='incomplete',runs=[],summary={},scope='Original XPU versus candidate with ALL XPU2 flags removed; enabled multiworker rendering is not qualified.',performance_gate={'relative_median_overhead':0.03,'absolute_median_overhead_seconds':0.1})
 def save():(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
 try:
  build=a.build.resolve();runtime=build/'runtime';reference=a.reference.resolve()
  b=json.loads((build/'report.json').read_text())
  if b['status']!='built' or digest_file(runtime/'librendering_rndr.dll')!=b['dll_sha256']:raise ValueError('Candidate drift')
  sources={**b['source_hashes'],**b['native_hashes']}
  for f in (build/'report.json',Path(__file__),a.scene.resolve()):sources[str(f)]=digest_file(f)
  for f,h in sources.items():
   if digest_file(Path(f))!=h:raise ValueError('Source drift '+f)
  locked={str(rt):inventory(rt) for rt in (runtime,reference)};identity=gpu_identity()
  report.update(source_hashes=sources,gpu=identity,logical_cpus=os.cpu_count(),requested_threads=[1,a.threads])
  scene=out/'scene.rdla';scene.write_bytes(a.scene.read_bytes());baselines={}
  order=[(t,label) for t in (1,a.threads) for label in ('reference','disabled')]
  for n in range(a.repeats+1):
   for threads,label in order[n%len(order):]+order[:n%len(order)]:
    folder=out/f'{n}-{threads}-{label}';folder.mkdir();rt=reference if label=='reference' else runtime
    env=environment(rt,folder)
    for key in list(env):
     if key.startswith('XPU2_') or key.startswith('MOONRAY_MODO_SESSION') or key=='MOONRAY_MODO_GENERATION':del env[key]
    if any(k.startswith('XPU2_') for k in env):raise ValueError('Experimental settings leaked')
    before=competing_renderers()
    if before:raise ValueError('Timing blocked by competing renderer '+str(before))
    print(n,threads,label,flush=True);start=time.perf_counter()
    with (folder/'render.log').open('w') as log:
     proc=subprocess.Popen([str(rt/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads',str(threads),'-info','-stats',str(folder/'stats.csv')],cwd=folder,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
     try:proc.wait(timeout=600)
     finally:
      if proc.poll() is None:proc.kill();proc.wait(timeout=10)
    elapsed=time.perf_counter()-start;after=competing_renderers();logs=(folder/'render.log').read_text(errors='replace')
    result=successful('xpu',threads,proc.returncode,logs,(folder/'stats.csv').read_text(errors='replace') if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
    row=dict(round=n,threads=threads,label=label,seconds=elapsed,execution=result,activity_before=before,activity_after=after,xpu2_configuration={});report['runs'].append(row);save()
    if after:raise ValueError('Timing contaminated')
    if not result['passed']:raise ValueError('Renderer failed')
    active=[line for line in logs.splitlines() if 'XPU2_' in line or '@@XPU2' in line]
    row['experimental_log_lines']=active
    if active:raise ValueError('Disabled renderer reported experimental activity')
    rgba=read_rgba(rt,folder/'beauty.exr',folder,'raw',env)
    if threads not in baselines:baselines[threads]=rgba
    row['comparison']=compare_rgba(baselines[threads],rgba,absolute=1e-6,relative=1e-6)
    if threads==1 and row['comparison']['exactly_different_pixels']:raise ValueError('Disabled single-worker image changed')
    save()
  for threads in (1,a.threads):
   result={}
   for label in ('reference','disabled'):
    rows=[r for r in report['runs'] if r['round'] and r['threads']==threads and r['label']==label]
    values=[r['execution']['renderer_timings_seconds']['Mcrt time'] for r in rows]
    result[label]=dict(mcrt_median=statistics.median(values),mcrt_min=min(values),mcrt_max=max(values),wall_median=statistics.median(r['seconds'] for r in rows),values=values,exact_images=all(not r['comparison']['exactly_different_pixels'] for r in rows))
   ref=result['reference']['mcrt_median'];off=result['disabled']['mcrt_median']
   result['overhead_seconds']=off-ref;result['overhead_fraction']=off/ref-1
   result['overhead_gate_passed']=off-ref<=max(.1,.03*ref)
   result['image_scope']='Exact' if threads==1 else 'Nondeterministic multiworker differences reported; no statistical parity qualification'
   report['summary'][str(threads)]=result
  for rt in (runtime,reference):verify(rt,locked[str(rt)])
  for f,h in sources.items():
   if digest_file(Path(f))!=h:raise ValueError('Source drift after run '+f)
  if gpu_identity()!=identity:raise ValueError('GPU changed')
  report['status']='passed' if all(s['overhead_gate_passed'] for s in report['summary'].values()) else 'overhead_regression'
 except Exception as exc:report['error']=str(exc)
 save();print(report['status'],report.get('error',''),flush=True)
 return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
