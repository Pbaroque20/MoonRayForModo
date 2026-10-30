import argparse,json
from pathlib import Path
from native_build import build
from reference_runtime import sha
HERE=Path(__file__).resolve().parent
p=argparse.ArgumentParser()
for n in ('source','runtime','output'):p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();src=a.source.resolve();rt=a.runtime.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
files=list(HERE.glob('*.h'))+[HERE/'residency_probe.cc',HERE/'native_build.py'];held={str(f):sha(f) for f in files}
r={'status':'incomplete','source_hashes':held}
try:
 inc=[src/'toolchain/xpu/optix-dev/include',src/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
 exe,r['build']=build(src,HERE/'residency_probe.cc',out/'native',[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc]);r['exe']=str(exe)
 if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Compiled source drift')
 r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e))
(out/'build.json').write_text(json.dumps(r,indent=2)+'\n');print(r['status'],r.get('error',''),flush=True)
raise SystemExit(int(r['status']!='passed'))
