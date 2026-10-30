"""Compare resident CPU workers with an owned, coalescing GPU queue.

One-thread images require exact RGBA. Multi-thread diagnostics retain exact
comparisons and separately enforce a predeclared 1e-6 absolute/relative bound.
Native-repeat disagreement is reported; this never certifies bitwise parity.
"""
import argparse,json,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2.fused_film_evidence import validate_fused
from xpu2.coalesced_film_evidence import validate_queue
from xpu2_baseline import environment
from xpu2_repeatability import successful,gpu_identity

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('build','base','output'):p.add_argument('--'+name,type=Path,required=True)
 p.add_argument('--threads',type=int,choices=(1,4,6),default=1)
 p.add_argument('--showcase',action='store_true');p.add_argument('--faults',action='store_true')
 a=p.parse_args();build,base,out=a.build.resolve(),a.base.resolve(),a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 report=dict(status='incomplete',threads=a.threads,gpu=gpu_identity(),runs=[],tolerance=dict(absolute=0 if a.threads==1 else 1e-6,relative=0 if a.threads==1 else 1e-6),scope='Resident native workers; copied fused numeric jobs; one GPU worker; no path migration')
 try:
  manifest=json.loads((build/'report.json').read_text());assert manifest['status']=='built' and manifest['fused']
  for name,wanted in manifest['files'].items():
   if digest_file(build/name)!=wanted:raise ValueError('Candidate build drift')
  report['build_manifest_sha256']=digest_file(build/'report.json')
  runtime=build/'runtime';reference=base/'control';locked=inventory(runtime);ref_locked=inventory(reference)
  original=ROOT/'test-results/xpu2-owned-contribution-validation/control/scene.rdla'
  old=json.loads((original.parent.parent/'report.json').read_text())
  if old['status']!='passed' or digest_file(original)!=old['renders'][0]['scene_sha256']:raise ValueError('Scene drift')
  scene=out/'scene.rdla'
  if a.showcase:
   from xpu2.film_showcase import scene as showcase
   scene.write_text(showcase(original.read_text()),encoding='utf-8')
  else:scene.write_bytes(original.read_bytes())
  report['scene_sha256']=digest_file(scene)
  cases=['reference','reference_repeat','blocking','fast','blocking_repeat','repeat','audit']
  if a.faults:cases+=['missing','bad_shader','sentinel']
  images={}
  for label in cases:
   native=label.startswith('reference');coalesced=not native and not label.startswith('blocking')
   mode=label if label in ('audit','sentinel') else 'fast'
   folder=out/label;folder.mkdir();rt=reference if native else runtime;env=environment(rt,folder)
   if not native:
    env.update(XPU2_NATIVE_LAMBERT='replace',XPU2_NATIVE_LAMBERT_PTX=str(ROOT/'test-results/xpu2-ray-image-final/sampler.ptx'),XPU2_SHADER_AUDIT='1',XPU2_PROFILE_QUIET='1',XPU2_FUSED_FILM='1',XPU2_FILM_CONTRIBUTION=mode,XPU2_FILM_PTX=str(folder/'missing.ptx' if label=='missing' else build/'film.ptx'),XPU2_FILM_PROFILE=str(folder/'film.json'),XPU2_NATIVE_BATCH_WIDTH='16',XPU2_WINDOW_DISPATCH='1',XPU2_NATIVE_LIGHT_OVERLAP='1',XPU2_PROFILE_FILE=str(folder/'shading.json'))
   if coalesced:env.update(XPU2_FILM_COALESCE='1',XPU2_FILM_QUEUE_PROFILE=str(folder/'queue.json'))
   if label=='bad_shader':env['XPU2_FUSED_BAD_REFERENCE']='1'
   print(label,flush=True);started=time.perf_counter()
   with (folder/'render.log').open('w') as log:
    run=subprocess.run([str(rt/'moonray.exe'),'-in',str(scene),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads',str(a.threads),'-info','-stats',str(folder/'stats.csv')],cwd=folder,env=env,stdout=log,stderr=log,timeout=240,creationflags=subprocess.CREATE_NO_WINDOW)
   elapsed=time.perf_counter()-started
   check=successful('xpu',a.threads,run.returncode,(folder/'render.log').read_text(errors='replace'),(folder/'stats.csv').read_text() if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
   row=dict(label=label,wall_seconds=elapsed,execution=check,log_sha256=digest_file(folder/'render.log'));report['runs'].append(row)
   if not check['passed']:raise ValueError('Native execution failed: '+label)
   images[label]=read_rgba(rt,folder/'beauty.exr',folder,'raw',env)
   exact=compare_rgba(images['reference'],images[label]);row['exact_image']=exact
   row['bounded_image']=compare_rgba(images['reference'],images[label],**report['tolerance'])
   if label=='sentinel':
    if not exact['exactly_different_pixels']:raise ValueError('GPU sentinel absent from film')
   elif row['bounded_image']['status']!='passed':raise ValueError('Image bound failed: '+label)
   if not native:
    fp=json.loads((folder/'film.json').read_text());row['film']=fp
    if (folder/'shading.json').exists():raise ValueError('Separate shading queue unexpectedly active')
    validation=label if label in ('audit','sentinel','missing','bad_shader') else 'fast'
    row['validation']=validate_fused(fp,validation)
    if fp['async_enabled'] or fp['graph_enabled']:raise ValueError('Unexpected transfer mode')
    if coalesced:
     qp=json.loads((folder/'queue.json').read_text());row['queue']=qp;row['queue_validation']=validate_queue(qp,fp,validation,a.threads)
   (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
  rows={r['label']:r for r in report['runs']}
  for block,queued in [('blocking','fast'),('blocking_repeat','repeat')]:
   for key in ('eligible','accepted','cpu_skipped','packets'):
    if rows[block]['film'][key]!=rows[queued]['film'][key]:raise ValueError('Completed work differs: '+key)
  verify(runtime,locked);verify(reference,ref_locked)
  if gpu_identity()!=report['gpu']:raise ValueError('GPU identity drift')
  report.update(status='passed',bitwise_parity=all(r['exact_image']['status']=='passed' for r in report['runs'] if r['label']!='sentinel'),speedup_established=False)
 except Exception as exc:report['error']=str(exc)
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(report['status'],report.get('error',''),flush=True)
 return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
