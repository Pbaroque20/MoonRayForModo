"""Bounded local shader recovery qualification using the real controller and lanes."""
import argparse,json,subprocess,sys,traceback
from pathlib import Path
from native_build import build
from reference_runtime import sha,verify
from reference_repeatability import save,values,distance
from run_material_progressive import call
from run_m0 import guard
HERE=Path(__file__).resolve().parent;TR=HERE.parents[1]/'test-results'
p=argparse.ArgumentParser()
for n in ('source','runtime','build','output'):p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();src=a.source.resolve();rt=a.runtime.resolve();OUT=a.output.resolve();OUT.mkdir(exist_ok=False);b=json.loads(a.build.read_text());ptx=Path(b['ptx']);r={'status':'incomplete','checks':{}}
try:
 guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()),4);assert all(sha(Path(k))==v for k,v in b['source_hashes'].items());assert sha(ptx)==b['binary_hashes']['ptx'];r['build']=str(a.build.resolve());r['source_hashes']=b['source_hashes']
 inc=[src/'toolchain/xpu/optix-dev/include',src/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
 def exe(unit,folder):
  e,v=build(src,HERE/unit,OUT/folder,[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc]);r.setdefault('builds',{})[folder]=v;return e
 def command(script,args,label,timeout=900):
  cmd=[sys.executable,HERE/script,*args];v=subprocess.run(list(map(str,cmd)),cwd=HERE.parents[1],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW);(OUT/(label+'.log')).write_text(v.stdout+v.stderr,encoding='utf-8');assert v.returncode==0,v.stdout[-1600:]+v.stderr[-1000:]
 command('run_sample_core.py',['--source',src,'--output',OUT/'qmc','--suite','qmc','--tuples',16777216,'--threads',12],'qmc');q=json.loads((OUT/'qmc/report.json').read_text());assert q['mismatches']==0;r['checks']['sampler']={'tuples_compared':q['tuples_compared'],'mismatches':q['mismatches'],'cpu_check_mask':q['cpu_check_mask'],'gpu_check_mask':q['gpu_check_mask'],'billion_tuple_qualification':q['tuples_gate']};save(OUT/'report.json',r);print('16,777,216 CPU/GPU sampler words and float conversions identical',flush=True)
 e=exe('material_progressive_probe.cc','planar-build');d=OUT/'planar';d.mkdir();f=TR/'interactive-material-progressive-20261022c/emission/frozen';r['checks']['planar']=json.loads(call([e,f/'scene.rdlb',rt,ptx,d,f],rt,d,'native',timeout=600));control=values((d/'cpu1.rgba').read_bytes());assert (d/'cpu1.rgba').read_bytes()==(d/'cpu12.rgba').read_bytes()
 for label in ('mixed','progressive','recovered','post-failure'):assert distance(control,values((d/(label+'.rgba')).read_bytes()))<=1e-6
 print('planar progressive/cancellation/recovery passed',flush=True);save(OUT/'report.json',r)
 e=exe('spatial_probe.cc','spatial-build');r['checks']['spatial']={}
 for key in ('f0-d0','f0-d2','f17-d2','f59-d2','f0-d2-zero-plane','f59-d7-emission'):
  f=TR/'interactive-ray-hit-multibounce-20261022'/key;d=OUT/key;d.mkdir();row=json.loads(call([e,f/'input.rdlb',rt,ptx,d],rt,d,'native',timeout=360));assert (d/'cpu.rgba').read_bytes()==(d/'gpu.rgba').read_bytes()==(f/'cpu.rgba').read_bytes();r['checks']['spatial'][key]={'probe':row,'byte_identical_to_baseline':True};save(OUT/'report.json',r);print(key,'passed',flush=True)
 # Compatibility manifest for the existing shader-input inventory contract.
 manifest=OUT/'ptx-build.json';save(manifest,{'status':'passed','ptx':b['ptx'],'build':b['cuda_build'],'source_hashes':b['source_hashes']})
 command('run_residency_recovery.py',['--source',src,'--runtime',rt,'--ptx-build',manifest,'--baseline',TR/'interactive-speed-20261022','--output',OUT/'residency'],'residency');r['checks']['residency']=json.loads((OUT/'residency/report.json').read_text());save(OUT/'report.json',r);print('texture misses, continuation validation, cancellation and recovery passed',flush=True)
 command('run_residency_controller.py',['--build',a.build.resolve(),'--runtime',rt,'--manifest',TR/'interactive-speed-20261022/room-close/grid-8/frozen/manifest.json','--previous',TR/'interactive-prototype-20261022c/report.json','--output',OUT/'controller'],'controller');r['checks']['controller']=json.loads((OUT/'controller/report.json').read_text());print('progressive controller, cached textures, whole-scene reference fallback and shutdown passed',flush=True)
 assert all(sha(Path(k))==v for k,v in b['source_hashes'].items());guard();verify(rt,json.loads((HERE/'reference-lock.json').read_text()),4);r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='passed')
