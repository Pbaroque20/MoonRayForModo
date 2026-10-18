"""Run bounded continuation contracts using the native fast-math compilation mode."""
import argparse,json,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_baseline import environment

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('source','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();source,out=a.source.resolve(),a.output.resolve()
    if out.is_relative_to(source):p.error('Isolated output required')
    out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete'}
    try:
        compiler=source/'toolchain/msys64/ucrt64/bin/g++.exe';env=environment(compiler.parent,out)
        files=[ROOT/'xpu2/deferred_film.h',ROOT/'xpu2/deferred_film_test.cc',Path(__file__).resolve()]
        hashes={str(f.relative_to(ROOT)):digest_file(f) for f in files}
        flags=['-std=c++17','-O2','-ffast-math','-mavx','-mno-avx2','-mno-fma','-ffp-contract=off']
        pp=out/'contract.ii';exe=out/'contract.exe'
        for label,command in [('preprocess',[str(compiler),*flags,'-E',str(files[1]),'-o',str(pp)]),('compile',[str(compiler),*flags,str(pp),'-o',str(exe)]),('run',[str(exe)])]:
            done=subprocess.run(command,env=env,cwd=out,capture_output=True,text=True,timeout=90,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(label+'.log')).write_text(done.stdout+done.stderr)
            if done.returncode:raise ValueError(label+' failed')
        checks=json.loads(done.stdout)
        if checks['status']!='passed':raise ValueError('Incomplete contract run')
        if hashes!={str(f.relative_to(ROOT)):digest_file(f) for f in files}:raise ValueError('Source drift')
        report.update(status='passed',checks=checks,flags=flags,source_hashes=hashes,compiler_sha256=digest_file(compiler),preprocessed_sha256=digest_file(pp),executable_sha256=digest_file(exe))
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''),flush=True)
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
