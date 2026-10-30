"""Private texture admission/reuse checks; no image-quality qualification."""
import argparse,json,subprocess
from pathlib import Path
from native_build import build
from reference_runtime import sha,verify
from fallback import environment
import asset_snapshot
HERE=Path(__file__).resolve().parent

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for name in ('source','runtime','baseline','output'):p.add_argument('--'+name,type=Path,required=True)
 a=p.parse_args();src=a.source.resolve();rt=a.runtime.resolve();base=a.baseline.resolve();out=a.output.resolve()
 if out.is_relative_to(src) or out.is_relative_to(rt) or out.is_relative_to(base):p.error('Fresh isolated output required')
 out.mkdir(parents=True,exist_ok=False);report={'status':'incomplete'}
 try:
  verify(rt,json.loads((HERE/'reference-lock.json').read_text()));assert json.loads((base/'report.json').read_text())['status']=='passed'
  assets=base/'diffuse/frozen';scene=asset_snapshot.verify(assets/'manifest.json')
  held={str(f):sha(f) for f in list(HERE.glob('*.h'))+[HERE/'texture_admission_probe.cc',HERE/'run_texture_admission.py',HERE/'native_build.py',assets/'manifest.json']};report['source_hashes']=held
  exe,report['build']=build(src,HERE/'texture_admission_probe.cc',out/'build')
  r=subprocess.run([str(rt/'oiiotool.exe'),'--pattern','constant:color=0.2,0.4,0.8','64x64','3','--tile','16','16','-o',str(out/'unmipped.tx')],env=environment(rt,out),cwd=out,capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
  (out/'fixture.log').write_text(r.stdout+r.stderr,encoding='utf-8');assert r.returncode==0
  r=subprocess.run([str(exe),str(scene),str(rt),str(assets/'assets'),str(out),str(out/'unmipped.tx')],env=environment(rt,out),cwd=out,capture_output=True,text=True,timeout=60,creationflags=subprocess.CREATE_NO_WINDOW)
  (out/'probe.log').write_text(r.stdout+r.stderr,encoding='utf-8')
  if r.returncode:raise RuntimeError(r.stderr[-1500:])
  report['native']=json.loads(r.stdout)
  if any(sha(Path(k))!=v for k,v in held.items()):raise RuntimeError('Source drift')
  asset_snapshot.verify(assets/'manifest.json');verify(rt,json.loads((HERE/'reference-lock.json').read_text()));report['status']='passed'
 except Exception as e:report.update(status='failed',error=str(e))
 (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8');print(json.dumps({k:v for k,v in report.items() if k not in ('source_hashes','build')},indent=2))
 return int(report['status']!='passed')
if __name__=='__main__':raise SystemExit(main())
