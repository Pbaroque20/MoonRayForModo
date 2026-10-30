"""Build and exercise the preparatory batch contract; no renderer performance claim."""
import argparse,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from xpu2.reference import digest_file

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--compiler',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    compiler=a.compiler.resolve();env=dict(os.environ);env['PATH']=str(compiler.parent)+os.pathsep+env.get('PATH','')
    files=[ROOT/'xpu2/batch_transport.h',ROOT/'xpu2/batch_transport_test.cc',Path(__file__).resolve()]
    report={'status':'incomplete','source_hashes':{str(f):digest_file(f) for f in files},'compiler_sha256':digest_file(compiler),'runs':[]}
    try:
        for name,extra in [('normal',[]),('native_math',['-ffast-math','-mavx','-mno-avx2','-mno-fma'])]:
            exe=out/(name+'.exe');args=[str(compiler),'-std=c++17','-O2','-Wall','-Wextra','-Werror','-static',*extra,'-I'+str(ROOT/'xpu2'),str(files[1]),'-o',str(exe)]
            built=subprocess.run(args,env=env,capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
            (out/(name+'-build.log')).write_text(built.stdout+built.stderr)
            if built.returncode:raise ValueError(name+' build failed')
            ran=subprocess.run([str(exe)],env=env,capture_output=True,text=True,timeout=15,creationflags=subprocess.CREATE_NO_WINDOW)
            report['runs'].append({'label':name,'command':args,'returncode':ran.returncode,'stdout':ran.stdout,'stderr':ran.stderr,'exe_sha256':digest_file(exe)})
            if ran.returncode or not ran.stdout.startswith('PASS:'):raise ValueError(name+' contract failed')
        if any(digest_file(Path(f))!=h for f,h in report['source_hashes'].items()):raise ValueError('Source changed')
        report['status']='passed'
    except Exception as exc:report['error']=str(exc)
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(report['status'],report.get('error',''))
    return 0 if report['status']=='passed' else 1
if __name__=='__main__':raise SystemExit(main())
