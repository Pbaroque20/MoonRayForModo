import json,traceback,array
from pathlib import Path
from native_build import build
from reference_runtime import sha
from reference_repeatability import save,values,distance
from run_material_progressive import call
from run_m0 import guard
HERE=Path(__file__).resolve().parent;TR=HERE.parents[1]/'test-results';OUT=TR/'interactive-ray-hit-diagnostic-20261022';OUT.mkdir(exist_ok=False)
r={'status':'incomplete','frozen_internal_abs_bound':.002,'scope':'separate strict ownership gate; overall statistical quality gates remain distinct','cases':{}}
try:
 rt=TR/'interactive-reference-042';src=Path(__import__('os').environ['XPU2_TOOLCHAIN_ROOT']);b=json.loads((TR/'interactive-prototype-build-20261022residency/build.json').read_text());base=json.loads((TR/'interactive-residency-benchmark-20261022/report.json').read_text());fixtures=json.loads((TR/'interactive-large-scenes-20261022/report.json').read_text())
 inc=[src/'toolchain/xpu/optix-dev/include',src/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include'];exe,r['build']=build(src,HERE/'ray_hit_probe.cc',OUT/'native',[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc]);r['source_hashes']={str(p):sha(p) for p in [*HERE.glob('*.h'),HERE/'ray_hit_probe.cc',Path(__file__).resolve()]}
 for name,c in base['cases'].items():
  folder=OUT/name;folder.mkdir();arms=c['arms'];old=values(Path(arms['t12-r0-p33']['runs'][0]['raw_file']).read_bytes());new=values(Path(arms['t12-r1-p33']['runs'][0]['raw_file']).read_bytes());outliers=[i for i in range(len(old)//4) if max(abs(old[i*4+k]-new[i*4+k]) for k in range(3))>.002];selected=folder/'pixels.json';save(selected,outliers);scene=Path(fixtures['cases'][name]['scenes']['8']);guard();data=json.loads(call([exe,scene,rt,b['ptx'],scene.parent/'assets',folder,selected],rt,folder,'probe',timeout=180));guard()
  r['cases'][name]={'outlier_pixels':outliers,'max_channel_delta':distance(old,new),'strict_gate_passed':distance(old,new)<=.002,'display_cadence_byte_identical':arms['t12-r1-p0']['runs'][0]['raw_sha256']==arms['t12-r1-p33']['runs'][0]['raw_sha256'],'worker_count_byte_identical':arms['t1-r1-p33']['runs'][0]['raw_sha256']==arms['t12-r1-p33']['runs'][0]['raw_sha256'],'stage_diagnostic':data};save(OUT/'report.json',r);print(name,'outlier pixels',len(outliers),'visibility disagreements',data['same_state_visibility_disagreements'],flush=True)
 r['strict_gate_passed']=all(c['strict_gate_passed'] for c in r['cases'].values());r['status']='measured';r['all_qualification_gates_passed']=False
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='measured')
