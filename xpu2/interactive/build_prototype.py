"""Build an isolated private prototype worker; never install or publish."""
import argparse,json
from pathlib import Path
from native_build import build
from gpu_build import compile_ptx
from reference_runtime import sha,verify
HERE=Path(__file__).resolve().parent

def build_all(source,runtime,out):
    source,runtime,out=map(lambda p:Path(p).resolve(),(source,runtime,out));out.mkdir(exist_ok=False,parents=True)
    verify(runtime,json.loads((HERE/'reference-lock.json').read_text()))
    files=list(HERE.glob('*.h'))+[HERE/n for n in ('prototype_worker.cc','gpu_trace.cu','gpu_build.py','native_build.py','build_prototype.py','asset_scene.cc')]
    held={str(p):sha(p) for p in files};report={'status':'incomplete','source_hashes':held}
    try:
        ptx,report['cuda_build']=compile_ptx(source,out)
        inc=[source/'toolchain/xpu/optix-dev/include',source/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
        exe,report['native_build']=build(source,HERE/'prototype_worker.cc',out/'native',[runtime/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc])
        helper,report['asset_build']=build(source,HERE/'asset_scene.cc',out/'assets')
        if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Build source drift')
        report.update(status='passed',exe=str(exe),ptx=str(ptx),helper=str(helper),binary_hashes={'exe':sha(exe),'ptx':sha(ptx)})
    except Exception as error:report.update(status='failed',error=str(error))
    (out/'build.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');return report
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source','runtime','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();r=build_all(a.source,a.runtime,a.output);print(json.dumps({k:v for k,v in r.items() if k in ('status','error','exe','ptx','helper')},indent=2),flush=True);raise SystemExit(r['status']!='passed')
