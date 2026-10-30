"""Private background CPU/OptiX service and explicit canonical fallback handoff."""
import argparse,array,json,subprocess,time
from pathlib import Path
from native_build import build
from gpu_build import compile_ptx
from fallback import environment
from fallback_service import ReferenceService
from protocol_model import Epoch
from reference_runtime import sha,verify
from run_m0 import guard
from run_cpu_image import compare_fixture
from xpu2.images import read_rgba,compare_rgba
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('source','runtime','baseline','output'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();source=a.source.resolve();rt=a.runtime.resolve();base=a.baseline.resolve();out=a.output.resolve()
 if out.is_relative_to(source) or out.is_relative_to(rt):p.error('Fresh isolated output required')
 out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete','scope':'experimental planar CPU/OptiX service, explicit sidecar handoff; no Modo or speed qualification'}
 try:
  guard();lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock)
  assert json.loads((base/'report.json').read_text())['status']=='passed'
  gates=json.loads((HERE/'surface-gates.json').read_text());gates.update(pending=4,results=2,retirement=4,stale='never publish',failure='no native pixels; reference fallback',fallback='exact float32 RGBA at one reference worker',recovery='new GPU context; valid mixed image',shutdown='release owned resources on feeder')
  (out/'frozen-gates.json').write_text(json.dumps(gates,indent=2),encoding='utf-8');report['gates']=gates
  files=list(HERE.glob('*.h'))+[HERE/n for n in ('mixed_service_probe.cc','gpu_trace.cu','gpu_build.py','native_build.py','run_mixed_service.py','run_cpu_image.py','surface-gates.json','fallback.py','fallback_service.py','reference_runtime.py','reference-lock.json','protocol_model.py')]+[base/n for n in ('report.json','initial/scene.rdlb','material.rgba','reference-material/beauty.exr')]+[ROOT/'xpu2'/n for n in ('rdl_scene_index.h','rdl_replica.h','indexed_scene.h','persistent_map.h')]
  held={str(f):sha(f) for f in files};report['source_hashes']=held
  ptx,nv=compile_ptx(source,out);report['cuda_build']=nv
  inc=[source/'toolchain/xpu/optix-dev/include',source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
  exe,native=build(source,HERE/'mixed_service_probe.cc',out/'build',[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc]);report['native_build']=native
  done=subprocess.run([str(exe),str(base/'initial/scene.rdlb'),str(rt),str(ptx),str(out)],cwd=out,env=environment(rt,out),capture_output=True,text=True,timeout=360,creationflags=subprocess.CREATE_NO_WINDOW)
  (out/'probe.log').write_text(done.stdout+done.stderr,encoding='utf-8')
  if done.returncode:raise RuntimeError('Native service failed: '+done.stderr[-1800:])
  report['native']=json.loads(done.stdout)
  if report['native']['status']!='passed':raise RuntimeError('Native checks failed')
  reference=read_rgba(rt,base/'reference-material/beauty.exr',out,'reference',environment(rt,out))
  report['images']={}
  for n in ('material','recovered'):
   path=out/(n+'.rgba');values=array.array('f');values.frombytes(path.read_bytes())
   report['images'][n]={'sha256':sha(path),'moonray_reference_errors':compare_fixture(values,reference,gates),'exact_against_cpu_fixture':path.read_bytes()==(base/'material.rgba').read_bytes()}
  # The failed native epoch is discarded in full. Its owned canonical RDLB
  # goes unchanged to the existing reference service, after GPU shutdown.
  guard();service=ReferenceService(rt,lock,out/'fallback')
  try:
   epoch=Epoch(**report['native']['failure_epoch']);ticket=service.request(out/'failure/scene.rdlb',epoch,1)
   deadline=time.monotonic()+180
   while True:
    state=service.poll()
    if state.phase=='failed':raise RuntimeError(state.error)
    if state.result is not None:break
    if time.monotonic()>deadline:raise TimeoutError('Reference service timeout')
    time.sleep(.01)
   if state.ticket!=ticket or state.result.epoch!=epoch or state.result.tier!='F' or state.result.actual_mode!='xpu':raise RuntimeError('Reference packet identity')
   actual=read_rgba(rt,state.result.image,out,'fallback-result',environment(rt,out))
   comparison=compare_rgba(reference,actual)
   if comparison['status']!='passed':raise RuntimeError('Fallback differs from pinned standalone reference')
   report['fallback']={'canonical_sha256':sha(out/'failure/scene.rdlb'),'tier':state.result.tier,'actual_mode':state.result.actual_mode,'comparison':comparison,'handoff':'explicit harness dispatch after failed native packet; production route remains fallback-only'}
  finally:
   service.close()
   if not service.wait_closed(15):raise RuntimeError('Reference service did not close')
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
  verify(rt,lock);report['status']='passed'
 except Exception as error:report.update(status='failed',error=str(error))
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k not in ('source_hashes','cuda_build','native_build','images')},indent=2),flush=True)
 return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
