"""Render native controls and capture bounded direct-light numerical packets."""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file,inventory,verify
from xpu2.images import read_rgba,compare_rgba
from xpu2_baseline import environment
from xpu2_repeatability import successful

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('build','reference','scene','output'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
 report={'status':'incomplete','runs':[]}
 try:
  build=a.build.resolve();m=json.loads((build/'report.json').read_text());rt=build/'runtime';ref=a.reference.resolve()
  if m['status']!='built' or digest_file(rt/'librendering_rndr.dll')!=m['dll_sha256']:raise ValueError('Build drift')
  sources={**m['source_hashes'],**m['native_hashes']}
  sources.update({str(a.scene.resolve()):digest_file(a.scene),str(Path(__file__).resolve()):digest_file(Path(__file__)),str(build/'report.json'):digest_file(build/'report.json')})
  for f,h in sources.items():
   if digest_file(Path(f))!=h:raise ValueError('Source drift '+f)
  held={str(r):inventory(r) for r in (rt,ref)};baseline=None
  for label,runtime in (('reference',ref),('capture',rt)):
   folder=out/label;folder.mkdir();env=environment(runtime,folder)
   for k in list(env):
    if k.startswith('XPU2_'):del env[k]
   if label=='capture':env['XPU2_LIGHT_CAPTURE']=str(folder/'light.bin')
   cmd=[str(runtime/'moonray.exe'),'-in',str(a.scene.resolve()),'-out',str(folder/'beauty.exr'),'-exec_mode','xpu','-threads','1','-info','-stats',str(folder/'stats.csv')]
   print(label,flush=True)
   with (folder/'render.log').open('w') as log:
    proc=subprocess.Popen(cmd,cwd=folder,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
    try:code=proc.wait(timeout=180)
    finally:
     if proc.poll() is None:proc.kill();proc.wait(timeout=10)
   check=successful('xpu',1,code,(folder/'render.log').read_text(errors='replace'),(folder/'stats.csv').read_text(errors='replace') if (folder/'stats.csv').exists() else '',(folder/'beauty.exr').exists())
   if not check['passed']:raise ValueError('Native render failed '+label)
   image=read_rgba(runtime,folder/'beauty.exr',folder,'raw',env)
   if baseline is None:baseline=image
   compare=compare_rgba(baseline,image,absolute=1e-6,relative=1e-6)
   report['runs'].append({'label':label,'comparison':compare,'execution':check})
   if compare['status']!='passed' or compare['exactly_different_pixels']:raise ValueError('Capture changed image')
  capture=out/'capture/light.bin';raw=capture.read_bytes()
  if raw[:4]!=b'XDL1' or (len(raw)-4)%160 or len(raw)==4:raise ValueError('Invalid/empty capture')
  counts=json.loads(capture.with_suffix('.bin.json').read_text());n=(len(raw)-4)//160
  if n!=sum(counts['written']) or any(v>65536 for v in counts['written']):raise ValueError('Capture accounting failed')
  for r in (rt,ref):verify(r,held[str(r)])
  for f,h in sources.items():
   if digest_file(Path(f))!=h:raise ValueError('Source drift '+f)
  report.update(status='passed',records=n,counts=counts,capture_sha256=digest_file(capture),source_hashes=sources,scope='Capture only; native shader results produce the image; no GPU output restoration or render-speed claim')
 except Exception as e:report['error']=str(e)
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
 return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
