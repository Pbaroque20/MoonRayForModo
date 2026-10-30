"""Private CPU/OptiX stage suspension, real images and epoch lifetime checks."""
import argparse,array,json,subprocess
from pathlib import Path
from native_build import build
from gpu_build import compile_ptx
from fallback import environment
from reference_runtime import sha,verify
from run_m0 import guard
from run_material_progressive import call
from run_cpu_image import compare_fixture
from xpu2.images import read_rgba
import asset_snapshot
HERE=Path(__file__).resolve().parent

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("--correctness-only-concurrent",action="store_true",help="Allow other renderer activity; no timing/performance evidence is collected")
 for name in ('source','runtime','baseline','output'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();src=a.source.resolve();rt=a.runtime.resolve();base=a.baseline.resolve();out=a.output.resolve()
 if any(out.is_relative_to(x) for x in (src,rt,base)):p.error('Fresh isolated output required')
 out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete','scope':'resumable planar path stages only; no general branching, migration or 30 ms qualification','cases':{}}
 try:
  if not a.correctness_only_concurrent:guard()
  report["concurrent_correctness_only"]=a.correctness_only_concurrent
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));assert json.loads((base/'report.json').read_text())['status']=='passed'
  gates=json.loads((HERE/'surface-gates.json').read_text());gates.update(resumed_native_max_error=0,max_cpu_jobs=24,max_gpu_slots=4,per_slice_gpu_allocations=0,per_slice_gpu_synchronizations=0,partial_sample_commits=0)
  (out/'frozen-gates.json').write_text(json.dumps(gates,indent=2),encoding='utf-8');report['gates']=gates
  files=list(HERE.glob('*.h'))+[HERE/n for n in ('deadline_probe.cc','run_deadlines.py','gpu_trace.cu','gpu_build.py','native_build.py','run_cpu_image.py')]+[base/'report.json']
  for name in ('emission','transformed','gamma','emission-map'):files += [base/name/'frozen/scene.rdlb',base/name/'frozen/manifest.json',base/name/'cpu1.rgba',base/name/'reference/beauty.exr']
  held={str(f):sha(f) for f in files};report['source_hashes']=held
  ptx,report['cuda_build']=compile_ptx(src,out)
  includes=[src/'toolchain/xpu/optix-dev/include',src/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
  exe,report['native_build']=build(src,HERE/'deadline_probe.cc',out/'build',[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(p) for p in includes])
  for name in ('emission','transformed','gamma','emission-map'):
   folder=out/name;folder.mkdir();assets=base/name/'frozen';asset_snapshot.verify(assets/'manifest.json')
   r=json.loads(call([exe,assets/'scene.rdlb',rt,ptx,folder,assets if name=='emission' else assets/'assets'],rt,folder,'native',timeout=360))
   report['cases'][name]={'native':r,'images':{}};expected=(base/name/'cpu1.rgba').read_bytes()
   reference=read_rgba(rt,base/name/'reference/beauty.exr',folder,'reference',environment(rt,folder))
   for f in folder.glob('*.rgba'):
    data=f.read_bytes();assert data==expected, 'Resumed or uninterrupted pixels changed: '+str(f)
    a=array.array('f');a.frombytes(data);report['cases'][name]['images'][f.stem]=compare_fixture(a,reference,gates)
   assert len(report['cases'][name]['images'])==(5 if name=='emission' else 3)
   asset_snapshot.verify(assets/'manifest.json');print('Passed resumable paths:',name,flush=True)
  if any(sha(Path(p))!=h for p,h in held.items()):raise RuntimeError('Source drift')
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));report['status']='passed'
 except Exception as e:report.update(status='failed',error=str(e))
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ('source_hashes','cuda_build','native_build','cases')},indent=2),flush=True)
 return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
