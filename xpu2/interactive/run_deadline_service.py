"""Private opt-in deadline service: progressive output, edits and failure recovery."""
import argparse,json
from pathlib import Path
from native_build import build
from gpu_build import compile_ptx
from reference_runtime import sha,verify
from run_m0 import guard
from run_material_progressive import call
import asset_snapshot
HERE=Path(__file__).resolve().parent

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument("--correctness-only-concurrent",action="store_true",help="Allow other renderer activity; no timing/performance evidence is collected")
 for name in ('source','runtime','baseline','output'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();src=a.source.resolve();rt=a.runtime.resolve();base=a.baseline.resolve();out=a.output.resolve()
 if any(out.is_relative_to(x) for x in (src,rt,base)):p.error('Fresh isolated output required')
 out.mkdir(parents=True,exist_ok=False);r={'status':'incomplete','scope':'private deadline background service; no Modo, hard latency or general material qualification'}
 try:
  if not a.correctness_only_concurrent:guard()
  r["concurrent_correctness_only"]=a.correctness_only_concurrent
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));assets=base/'emission/frozen';asset_snapshot.verify(assets/'manifest.json')
  r['gates']={'final':'exact native CPU float32 RGBA','stale_results':0,'error_pixels':0,'partial_with_unfinished_paths':True,'cpu_created_and_joined':12,'gpu_contexts':2,'discarded_cpu_jobs':0}
  (out/'frozen-gates.json').write_text(json.dumps(r['gates'],indent=2),encoding='utf-8')
  files=list(HERE.glob('*.h'))+[HERE/n for n in ('deadline_service_probe.cc','run_deadline_service.py','gpu_trace.cu','gpu_build.py','native_build.py')]+[assets/'scene.rdlb',assets/'manifest.json']
  held={str(f):sha(f) for f in files};r['source_hashes']=held
  ptx,r['cuda_build']=compile_ptx(src,out);inc=[src/'toolchain/xpu/optix-dev/include',src/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
  exe,r['native_build']=build(src,HERE/'deadline_service_probe.cc',out/'build',[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(x) for x in inc])
  r['native']=json.loads(call([exe,assets/'scene.rdlb',rt,ptx,out,assets],rt,out,'native',timeout=360))
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));r['status']='passed'
 except Exception as e:r.update(status='failed',error=str(e))
 (out/'report.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in r.items() if k not in ('source_hashes','cuda_build','native_build')},indent=2),flush=True)
 return int(r['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
