"""Render a portable sequence: python render_sequence.py --runtime PATH [--missing]."""
import argparse,hashlib,json,os,subprocess,tempfile,time
from pathlib import Path

def digest(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as stream:
  for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
 return h.hexdigest()

def inside(root,name):
 path=(root/name).resolve();path.relative_to(root.resolve());return path

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--runtime',type=Path,required=True)
 parser.add_argument('--package',type=Path,default=Path(__file__).resolve().parent)
 parser.add_argument('--mode',choices=['auto','xpu','vectorized','scalar'],default='auto')
 parser.add_argument('--threads',type=int,default=0)
 parser.add_argument('--missing',action='store_true')
 args=parser.parse_args();root=args.package.resolve();runtime=args.runtime.resolve();exe=runtime/'moonray.exe'
 if not exe.is_file():raise ValueError('Runtime is missing moonray.exe')
 if args.threads<0:raise ValueError('Thread count cannot be negative')
 manifest=root/'sequence.json';sequence=json.loads(manifest.read_text(encoding='utf-8'))
 if sequence.get('status')!='complete':raise ValueError('Finish collecting the sequence before rendering it')
 signature=digest(manifest)+digest(exe)+args.mode+str(args.threads)
 report=root/'render-state.json';saved=json.loads(report.read_text(encoding='utf-8')) if report.exists() else {}
 if saved and (not args.missing or saved.get('signature')!=signature):raise ValueError('Use --missing with the original package/runtime/settings, or a new output package')
 records=saved.get('frames',{})
 def save(status):
  stage=report.with_suffix('.tmp');stage.write_text(json.dumps({'signature':signature,'status':status,'frames':records},indent=2),encoding='utf-8');stage.replace(report)
 env=dict(os.environ);env['PATH']=str(runtime)+os.pathsep+env.get('PATH','');env['REZ_MOONRAY_ROOT']=str(runtime);env['TMPDIR']=tempfile.gettempdir()
 env['RDL2_DSO_PATH']=os.pathsep.join(str(p) for p in (runtime/'rdl2dso',runtime) if p.is_dir())
 for key in ('PYTHONHOME','PYTHONPATH','QT_PLUGIN_PATH','QT_QPA_PLATFORM_PLUGIN_PATH','MOONRAY_MODO_SESSION','MOONRAY_MODO_GENERATION','MOONRAY_MODO_BUCKETS'):env.pop(key,None)
 # Validate every frame and asset before launching a renderer.
 checked={}
 for entry in sequence['frames']:
  scene=inside(root,entry['scene'])
  if digest(scene)!=entry['sha256']:raise ValueError('Packaged scene changed: '+str(scene))
  assets=json.loads((scene.parent/'manifest.json').read_text(encoding='utf-8'))['assets']
  for asset in assets:
   path=inside(scene.parent,asset['file']);stat=path.stat();key=(stat.st_dev,stat.st_ino or str(path),stat.st_size,stat.st_mtime_ns)
   actual=checked.get(key)
   if actual is None:actual=checked[key]=digest(path)
   if actual!=asset['sha256']:raise ValueError('Packaged asset changed: '+str(path))
 for entry in sequence['frames']:
  scene=inside(root,entry['scene']);output=scene.parent/'output/beauty.exr';key=str(entry['frame']);record=records.get(key,{})
  if output.exists():
   if args.missing and record.get('sha256')==digest(output) and record.get('status')=='complete' and record.get('outputs') and all(inside(scene.parent,name).is_file() and digest(inside(scene.parent,name))==value for name,value in record['outputs'].items()):continue
   raise ValueError('Unverified existing output; preserve it in another folder before retrying: '+str(output))
  command=[str(exe),'-in',str(scene),'-out',str(output),'-exec_mode',args.mode,'-info']
  if args.threads:command+=['-threads',str(args.threads)]
  records[key]={'status':'rendering'};save('rendering');started=time.monotonic()
  with (scene.parent/'render.log').open('w',encoding='utf-8') as log:
   try:process=subprocess.Popen(command,cwd=str(scene.parent),env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
   except OSError as exc:
    records[key]={'status':'failed','error':str(exc)};save('failed');raise
   try:code=process.wait()
   except KeyboardInterrupt:
    process.terminate()
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait()
    records[key]={'status':'interrupted'};save('interrupted');raise
  valid=False
  if output.is_file() and output.stat().st_size>=32:
   with output.open('rb') as stream:valid=stream.read(4)==b'\x76\x2f\x31\x01'
  if code or not valid:records[key]={'status':'failed','exit_code':code};save('failed');raise RuntimeError('Render failed; inspect '+str(scene.parent/'render.log'))
  records[key]={'status':'complete','sha256':digest(output),'seconds':time.monotonic()-started,'outputs':{v.relative_to(scene.parent).as_posix():digest(v) for v in output.parent.rglob('*.exr') if v.is_file()}};save('rendering')
 save('complete')

if __name__=='__main__':main()
