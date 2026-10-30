"""Run allocation and concurrent-claim contracts for native light descriptors."""
import argparse,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from xpu2.reference import digest_file
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
files=[ROOT/'xpu2'/name for name in ('native_light_window.h','native_local_tile_policy.h','native_light_window_test.cc')]+[Path(__file__)]
held={str(f):digest_file(f) for f in files};report={'status':'incomplete','sources':held}
try:
 compiler=a.source.resolve()/'toolchain/msys64/ucrt64/bin/g++.exe';env=os.environ.copy();env['PATH']=str(compiler.parent)+os.pathsep+env['PATH'];exe=out/'contracts.exe'
 report['compiler_sha256']=digest_file(compiler)
 build=subprocess.run([str(compiler),'-std=c++17','-O2','-pthread','-I',str(ROOT/'xpu2'),str(ROOT/'xpu2/native_light_window_test.cc'),'-o',str(exe)],env=env,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
 (out/'compile.log').write_text(build.stdout+build.stderr)
 if build.returncode:raise ValueError('Contract compilation failed')
 run=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW);report['output']=run.stdout+run.stderr;report['returncode']=run.returncode
 if run.returncode:raise ValueError('Descriptor contract failed')
 for f,h in held.items():
  if digest_file(Path(f))!=h:raise ValueError('Contract source changed')
 report['status']='passed';report['executable_sha256']=digest_file(exe)
except Exception as exc:report['error']=str(exc)
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('output',report.get('error','')))
raise SystemExit(0 if report['status']=='passed' else 1)
