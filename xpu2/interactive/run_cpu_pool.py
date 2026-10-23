"""Private persistent CPU pool ownership, failure, parking and lifetime checks."""
import argparse,json,subprocess
from pathlib import Path
from native_build import build
from reference_runtime import sha,verify
from fallback import environment
HERE=Path(__file__).resolve().parent

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('source','runtime','baseline','output'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();src=a.source.resolve();rt=a.runtime.resolve();base=a.baseline.resolve();out=a.output.resolve()
 if out.is_relative_to(src) or out.is_relative_to(rt) or out.is_relative_to(base):p.error('Fresh isolated output required')
 out.mkdir(parents=True,exist_ok=False);r={'status':'incomplete','scope':'bounded same-process CPU transport, not SIMD/NUMA or render-speed qualification'}
 try:
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));assert json.loads((base/'report.json').read_text())['status']=='passed'
  scene=base/'initial/scene.rdlb';held={str(f):sha(f) for f in list(HERE.glob('*.h'))+[HERE/'cpu_pool_probe.cc',HERE/'run_cpu_pool.py',HERE/'native_build.py',scene]};r['source_hashes']=held
  r['gates']={'created_workers':12,'shutdown_joins':12,'max_outstanding_jobs':24,'result_match':'exact native job oracle','lost_duplicate_stale_results':0,'idle_workers_parked':12}
  (out/'frozen-gates.json').write_text(json.dumps(r['gates'],indent=2),encoding='utf-8')
  exe,r['build']=build(src,HERE/'cpu_pool_probe.cc',out/'build',[rt/'libembree4.dll'])
  done=subprocess.run([str(exe),str(scene),str(rt),str(out)],env=environment(rt,out),cwd=out,capture_output=True,text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
  (out/'probe.log').write_text(done.stdout+done.stderr,encoding='utf-8')
  if done.returncode:raise RuntimeError(done.stderr[-1800:])
  r['native']=json.loads(done.stdout)
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));r['status']='passed'
 except Exception as e:r.update(status='failed',error=str(e))
 (out/'report.json').write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in r.items() if k not in ('source_hashes','build')},indent=2),flush=True)
 return int(r['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
