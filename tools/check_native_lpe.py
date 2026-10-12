"""Exercise native LPE grammar acceptance and rejection with the configured runtime."""
import argparse,json,subprocess,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import native,lpe_validation,outputs
p=argparse.ArgumentParser();p.add_argument('runtime');p.add_argument('--output',default='test-results/native-lpe');args=p.parse_args()
runtime=Path(args.runtime).resolve();out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
expressions=['C.*L','diffuse','C(L|)']
assert outputs.lpe_problem(expressions[-1]) is None,'Fixture must exercise a gap in the fast checker'
with tempfile.TemporaryDirectory(prefix='moonray-lpe-check-') as folder:
 path=lpe_validation.prepare(folder,expressions)
 r=subprocess.run([str(runtime/'moonray.exe')]+native.arguments(path,Path(folder)/'beauty.exr',threads=1,mode='scalar'),env=native.environment(runtime),capture_output=True,text=True,timeout=60)
 log=r.stdout+r.stderr;(out/'native.log').write_text(log,encoding='utf-8')
 failed=lpe_validation.results(folder,len(expressions),r.returncode,log)
 assert set(failed)=={2},failed
(out/'report.json').write_text(json.dumps({'ok':True,'accepted':expressions[:2],'rejected':expressions[2:]},indent=2),encoding='utf-8')
print('Native LPE check: explicit expression and alias accepted; invalid alternative rejected')
