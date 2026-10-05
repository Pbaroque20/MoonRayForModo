"""Capture progressive frames from the saved artifact-reproduction snapshot."""
import argparse,json,queue,subprocess,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'kit/MoonRayForModo/python'))
from moonray_modo import native,rdla,shared_image
parser=argparse.ArgumentParser();parser.add_argument('runtime',type=Path);parser.add_argument('label');args=parser.parse_args()
base=ROOT/'test-results/progressive-artifacts';out=base/args.label;out.mkdir(exist_ok=False)
s=json.loads((base/'snapshot.json').read_text());s['preview_buffer_files']={};s['aovs']=[]
s['render_settings']['max_adaptive_samples']=64
source=out/'scene.rdla';source.write_text(rdla.scene_text(s,640,360,4,0,str(out/'final.exr')),encoding='utf-8')
env=native.environment(args.runtime);env.update(MOONRAY_MODO_SESSION=str(out),MOONRAY_MODO_GENERATION='1',MOONRAY_MODO_SHARED='1',MOONRAY_MODO_BUCKETS='1')
proc=subprocess.Popen([str(args.runtime/'moonray.exe')]+native.arguments(source,out/'final.exr',12,'auto'),env=env,cwd=out,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
messages=queue.Queue();start=time.monotonic();report={'frames':[],'runtime':str(args.runtime)}
def reader():
 for line in iter(proc.stdout.readline,b''):messages.put(line.decode('utf-8',errors='replace').strip())
 messages.put('EXIT')
thread=threading.Thread(target=reader,daemon=True);thread.start()
try:
 with (out/'render.log').open('w',encoding='utf-8') as log:
  while time.monotonic()-start<240:
   try:line=messages.get(timeout=1)
   except queue.Empty:continue
   log.write(line+'\n');log.flush()
   if line.startswith('@@MODO_SHARED '):
    _,key,w,h,data=shared_image.receive(line,proc.pid)
    number=len(report['frames']);path=out/('%03d.pfm'%number)
    path.write_bytes(('PF\n%d %d\n-1.0\n'%(w,h)).encode()+data)
    report['frames'].append({'file':str(path),'time':time.monotonic()-start})
   if line=='@@MODO_SESSION DONE 1':
    report['complete']=True;break
   if line=='EXIT':raise RuntimeError('Renderer exited before DONE')
  else:raise TimeoutError('Render exceeded 240 seconds')
finally:
 if proc.poll() is None:proc.kill();proc.wait(timeout=15)
 thread.join(timeout=5)
 (out/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps({'frames':len(report['frames']),'complete':report.get('complete',False),'folder':str(out)}))
