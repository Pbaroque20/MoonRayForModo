"""Private common-camera estimator ablation, not a production estimator promotion."""
import json,traceback,statistics
from pathlib import Path
from native_build import build
from reference_runtime import sha,verify
from reference_repeatability import save,values
from run_speed_comparison import metric
from run_material_progressive import call
from run_m0 import guard
import asset_snapshot
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];TR=ROOT/'test-results';OUT=TR/'interactive-estimator-ablation-20261022'
PLAN={'spp':64,'seeds':[3034297317,17,47],'camera':'identical Sobol jitter for every variant','direction_sampler':['Philox','Sobol digital shift'],'estimators':['1 cosine BSDF sample','mean of 2 cosine BSDF samples','power MIS: 1 cosine BSDF plus 1 uniform-sphere environment sample'],'shared_events':'same camera, intersection and material event per pixel/sample for all 6 variants','equal_work':'bsdf2 versus MIS use 2 directional attempts; BSDF1 uses one, so ray cost differs','control':'same previous original-XPU 1024spp reference, no gate relaxation','scope':'constant environment, diffuse+emission, one surface; own MIS test, not MoonRay port; component quality test, not timing benchmark'}
OUT.mkdir(exist_ok=False);save(OUT/'protocol.json',PLAN);r={'status':'incomplete','protocol':PLAN,'cases':{}}
try:
 src=Path(__import__('os').environ['XPU2_TOOLCHAIN_ROOT']);rt=TR/'interactive-reference-042';lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);guard()
 held={str(f):sha(f) for f in [*HERE.glob('*.h'),HERE/'estimator_ablation.cc',Path(__file__).resolve()]};r['source_hashes']=held
 exe,r['build']=build(src,HERE/'estimator_ablation.cc',OUT/'native',[rt/'libembree4.dll'])
 baseline=json.loads((TR/'interactive-speed-20261022/report.json').read_text())
 for name in ('room-resident','room-close'):
  d=OUT/name;d.mkdir();scene=asset_snapshot.verify(TR/'interactive-speed-20261022'/name/'grid-8/frozen/manifest.json');meta=baseline['cases'][name]['converged'];refp=Path(meta['folder'])/'beauty.rgba';assert sha(refp)==meta['raw_sha256'];ref=values(refp.read_bytes());c=r['cases'][name]={'seeds':{},'reference':meta}
  for seed in PLAN['seeds']:
   dest=d/str(seed);dest.mkdir();data=json.loads(call([exe,scene,rt,scene.parent/'assets',dest,seed],rt,dest,'probe',timeout=300));assert data['status']=='passed';c['seeds'][str(seed)]=data
   for label,path in data['images'].items():data.setdefault('errors',{})[label]=metric(values(Path(path).read_bytes()),ref,data['width'],data['height'])
   print(name,seed,{k:round(v['relative_mse'],8) for k,v in data['errors'].items()},flush=True);save(OUT/'report.json',r)
  c['median_relative_mse']={label:statistics.median(v['errors'][label]['relative_mse'] for v in c['seeds'].values()) for label in data['images']}
  m=c['median_relative_mse'];c['directional_sampler_ratio_bsdf1']=m['sobol-bsdf1']/m['philox-bsdf1'];c['mis_ratio_equal_direction_attempts']=m['sobol-mis']/m['sobol-bsdf2'];save(OUT/'report.json',r)
 assert all(sha(Path(k))==v for k,v in held.items());verify(rt,lock);guard();r['status']='measured'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='measured')
