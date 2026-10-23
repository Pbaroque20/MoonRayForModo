import json,sys,subprocess,traceback
from pathlib import Path
from native_build import build
from reference_runtime import sha,verify
from reference_repeatability import save,values,distance
from run_material_progressive import call
from run_m0 import guard
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];TR=ROOT/'test-results';OUT=TR/'interactive-startup-recovery-20261022';OUT.mkdir(exist_ok=False);rt=TR/'interactive-reference-042';src=Path(__import__('os').environ['XPU2_TOOLCHAIN_ROOT']);g=json.loads((TR/'interactive-startup-material-ptx-20261022/build.json').read_text());ptx=Path(g['ptx']);r={'status':'incomplete','checks':{}}
try:
 guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()));held={str(p):sha(p) for p in [*HERE.glob('*.h'),HERE/'gpu_trace.cu']};r['source_hashes']=held
 inc=[src/'toolchain/xpu/optix-dev/include',src/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
 def exe(unit,folder):
  e,b=build(src,HERE/unit,OUT/folder,[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc]);r[folder]=b;return e
 e=exe('material_progressive_probe.cc','planar-build');d=OUT/'planar';d.mkdir();f=TR/'interactive-material-progressive-20261022c/emission/frozen';r['checks']['planar']=json.loads(call([e,f/'scene.rdlb',rt,ptx,d,f],rt,d,'native',timeout=600));a=values((d/'cpu1.rgba').read_bytes());assert (d/'cpu1.rgba').read_bytes()==(d/'cpu12.rgba').read_bytes()
 for label in ('mixed','progressive','recovered','post-failure'):assert distance(a,values((d/(label+'.rgba')).read_bytes()))<=1e-6
 print('planar progressive/cancellation/recovery passed',flush=True);save(OUT/'report.json',r)
 e=exe('spatial_probe.cc','spatial-build');r['checks']['spatial']={}
 for key in ('f0-d0','f0-d2','f17-d2','f59-d2','f0-d2-zero-plane','f59-d7-emission'):
  f=TR/'interactive-ray-hit-multibounce-20261022'/key;d=OUT/key;d.mkdir();row=json.loads(call([e,f/'input.rdlb',rt,ptx,d],rt,d,'native',timeout=360));assert (d/'cpu.rgba').read_bytes()==(d/'gpu.rgba').read_bytes()==(f/'cpu.rgba').read_bytes();r['checks']['spatial'][key]={'probe':row,'byte_identical_to_baseline':True};save(OUT/'report.json',r);print(key,'passed',flush=True)
 cmd=[sys.executable,HERE/'run_residency_recovery.py','--source',src,'--runtime',rt,'--ptx-build',TR/'interactive-startup-material-ptx-20261022/build.json','--baseline',TR/'interactive-speed-20261022','--output',TR/'interactive-startup-residency-20261022']
 v=subprocess.run(list(map(str,cmd)),cwd=ROOT,capture_output=True,text=True,timeout=900,creationflags=subprocess.CREATE_NO_WINDOW);(OUT/'residency.log').write_text(v.stdout+v.stderr,encoding='utf-8');assert not v.returncode,v.stdout[-1500:];r['checks']['residency']=json.loads((TR/'interactive-startup-residency-20261022/report.json').read_text());print('texture residency/cancellation/recovery passed',flush=True)
 assert all(sha(Path(k))==v for k,v in held.items());guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()));r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='passed')
