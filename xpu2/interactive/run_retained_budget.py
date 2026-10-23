"""Private native retained-scene admission check; no rendering or installation."""
import argparse
import json
from pathlib import Path
import subprocess
from native_build import build
from reference_runtime import sha,verify
from fallback import environment
HERE=Path(__file__).resolve().parent

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','runtime','scene','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    source,runtime,scene,out=[getattr(args,n).resolve() for n in ('source','runtime','scene','output')]
    if out.is_relative_to(source) or out.is_relative_to(runtime):parser.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete'}
    try:
        lock=json.loads((HERE/'reference-lock.json').read_text());verify(runtime,lock)
        held={str(HERE/n):sha(HERE/n) for n in ('canonical_session.h','snapshot_budget.h','canonical_budget_test.cc','native_build.py','run_retained_budget.py')}
        exe,metadata=build(source,HERE/'canonical_budget_test.cc',out/'build')
        env=environment(runtime,out)
        r=subprocess.run([str(exe),str(scene),env['RDL2_DSO_PATH'],str(out)],env=env,cwd=out,capture_output=True,
                         text=True,timeout=120,creationflags=subprocess.CREATE_NO_WINDOW)
        (out/'probe.log').write_text(r.stdout+r.stderr,encoding='utf-8')
        if r.returncode:raise RuntimeError('Native check failed: '+r.stderr)
        report.update(status='passed',build=metadata,source_hashes=held,native=json.loads(r.stdout))
        if any(sha(Path(f))!=v for f,v in held.items()):raise RuntimeError('Source drift')
    except Exception as e:report.update(status='failed',error=str(e))
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(report['status'],report.get('error',''));return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
