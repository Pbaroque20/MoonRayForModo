"""Private post-timing correctness, continuation and fallback checks."""
import json,sys,subprocess,traceback
from pathlib import Path
from native_build import build
from reference_repeatability import save,values,distance
from reference_runtime import sha,verify
from run_material_progressive import call
from run_m0 import guard
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];TR=ROOT/'test-results';OUT=TR/'interactive-ray-hit-recovery-20261022';OUT.mkdir(exist_ok=False)
rt=TR/'interactive-reference-042';src=Path(__import__('os').environ['XPU2_TOOLCHAIN_ROOT']);ptx=TR/'interactive-ray-hit-shared-ptx-20261022/build.json';report={'status':'incomplete','checks':{}}
def script(name,**kwargs):
 cmd=[sys.executable,str(HERE/name)]
 for k,v in kwargs.items():cmd.extend(['--'+k.replace('_','-'),str(v)])
 r=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=1500,creationflags=subprocess.CREATE_NO_WINDOW)
 (OUT/(name+'.log')).write_text(r.stdout+r.stderr,encoding='utf-8')
 if r.returncode:raise RuntimeError(name+' failed: '+(r.stdout+r.stderr)[-1000:])
 result=json.loads((Path(kwargs['output'])/('build.json' if name=='build_prototype.py' else 'report.json')).read_text());assert result['status']=='passed';report['checks'][name]={'status':'passed','output':str(kwargs['output'])};save(OUT/'report.json',report);print(name,'passed',flush=True)
try:
 guard();lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);report['source_hashes']={str(p):sha(p) for p in [*HERE.glob('*.h'),HERE/'gpu_trace.cu',Path(__file__).resolve(),HERE/'triangle_contract_probe.cc']}
 inc=[src/'toolchain/xpu/optix-dev/include',src/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'];exe,report['contract_build']=build(src,HERE/'triangle_contract_probe.cc',OUT/'contract',[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc]);report['checks']['triangle_contract']=json.loads(call([exe],rt,OUT,'contract'));print('triangle contract passed',flush=True);save(OUT/'report.json',report)
 planar=OUT/'planar';planar.mkdir();ex,report['planar_build']=build(src,HERE/'material_progressive_probe.cc',OUT/'planar-build',[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc]);fixture=TR/'interactive-material-progressive-20261022c/emission/frozen';g=json.loads(ptx.read_text());report['checks']['planar']=json.loads(call([ex,fixture/'scene.rdlb',rt,g['ptx'],planar,fixture],rt,planar,'probe',timeout=600));control=values((planar/'cpu1.rgba').read_bytes());assert (planar/'cpu1.rgba').read_bytes()==(planar/'cpu12.rgba').read_bytes()
 for label in ('mixed','progressive','recovered','post-failure'):assert distance(control,values((planar/(label+'.rgba')).read_bytes()))<=1e-6
 print('planar progressive regression passed',flush=True);save(OUT/'report.json',report)
 script('run_residency_recovery.py',source=src,runtime=rt,ptx_build=ptx,baseline=TR/'interactive-speed-20261022',output=TR/'interactive-ray-hit-refill-recovery-20261022')
 script('run_sampling_recovery.py',source=src,runtime=rt,ptx_build=ptx,baseline=TR/'interactive-speed-20261022',output=TR/'interactive-ray-hit-default-recovery-20261022')
 script('run_spatial.py',source=src,runtime=rt,output=TR/'interactive-ray-hit-multibounce-20261022')
 script('build_prototype.py',source=src,runtime=rt,output=TR/'interactive-prototype-build-20261022hits')
 script('run_residency_controller.py',build=TR/'interactive-prototype-build-20261022hits/build.json',runtime=rt,manifest=TR/'interactive-speed-20261022/room-close/grid-8/frozen/manifest.json',previous=TR/'interactive-prototype-20261022c/report.json',output=TR/'interactive-ray-hit-controller-20261022')
 assert all(sha(Path(k))==v for k,v in report['source_hashes'].items());verify(rt,lock);guard();report['status']='passed'
except Exception as e:report.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',report);print(report['status'],report.get('error',''),flush=True);raise SystemExit(report['status']!='passed')
