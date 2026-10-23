"""Private OptiX CPU/GPU execution and asynchronous ownership validation."""
import argparse,array,json,subprocess,math
from pathlib import Path
from native_build import build
from gpu_build import compile_ptx
from fallback import environment
from reference_runtime import sha,verify
from run_m0 import guard
from xpu2.images import read_rgba
from run_cpu_image import compare_fixture
HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('source','runtime','baseline','output'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();source=a.source.resolve();rt=a.runtime.resolve();base=a.baseline.resolve();out=a.output.resolve()
 if out.is_relative_to(source) or out.is_relative_to(rt):p.error('Isolated output required')
 out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete','scope':'unqualified planar diffuse CPU/OptiX image path; no performance claim'}
 try:
  guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()))
  baseline=json.loads((base/'report.json').read_text());assert baseline['status']=='passed'
  gates=json.loads((HERE/'surface-gates.json').read_text());gates.update(cpu_exact=True,max_gpu_flights=4,steady_state_sync=0,per_trip_allocations=0,counts='exact',invalid_epochs='no image',old_resident_error=1e-6)
  (out/'frozen-gates.json').write_text(json.dumps(gates,indent=2),encoding='utf-8');report['gates']=gates
  files=list(HERE.glob('*.h'))+[HERE/n for n in ('mixed_probe.cc','gpu_trace.cu','gpu_build.py','native_build.py','run_mixed.py','run_cpu_image.py','surface-gates.json')]+[base/'report.json',base/'initial/scene.rdlb']+[base/(n+'.rgba') for n in ('initial','material','camera','geometry')]+[base/('reference-'+n)/'beauty.exr' for n in ('initial','material','camera','geometry')]+[ROOT/'xpu2'/n for n in ('rdl_scene_index.h','rdl_replica.h','indexed_scene.h','persistent_map.h')]
  held={str(f):sha(f) for f in files};report['source_hashes']=held
  ptx,nv=compile_ptx(source,out);report['cuda_build']=nv
  inc=[source/'toolchain/xpu/optix-dev/include',source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
  exe,native=build(source,HERE/'mixed_probe.cc',out/'build',[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc]);report['native_build']=native
  done=subprocess.run([str(exe),str(base/'initial/scene.rdlb'),str(rt),str(ptx),str(out)],cwd=out,env=environment(rt,out),capture_output=True,text=True,timeout=360,creationflags=subprocess.CREATE_NO_WINDOW)
  (out/'probe.log').write_text(done.stdout+done.stderr,encoding='utf-8')
  if done.returncode:raise RuntimeError('Native GPU probe failed: '+done.stderr[-1800:])
  report['native']=json.loads(done.stdout)
  if report['native']['status']!='passed':raise RuntimeError('Native checks failed')
  report['images']={}
  references={n:read_rgba(rt,base/('reference-'+n)/'beauty.exr',out,'reference-'+n,environment(rt,out)) for n in ('initial','material','camera','geometry')}
  for path in out.glob('*.rgba'):
   label=path.stem;expected=label if label in ('material','camera','geometry') else 'initial'
   target=array.array('f');target.frombytes((base/(expected+'.rgba')).read_bytes());actual=array.array('f');actual.frombytes(path.read_bytes())
   if label in ('initial-cpu','initial-cpu12') and path.read_bytes()!=(base/'initial.rgba').read_bytes():raise RuntimeError('CPU job refactor differs')
   reference={'channels':{c:target[i::4] for i,c in enumerate('RGBA')}}
   report['images'][label]={'sha256':sha(path),'errors':compare_fixture(actual,reference,gates),'baseline':expected,'moonray_reference_errors':compare_fixture(actual,references[expected],gates)}
  if len(report['images'])!=10:raise RuntimeError('Missing expected image')
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));report['status']='passed'
 except Exception as error:report.update(status='failed',error=str(error))
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({k:v for k,v in report.items() if k not in ('source_hashes','cuda_build','native_build','images')},indent=2),flush=True)
 return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
