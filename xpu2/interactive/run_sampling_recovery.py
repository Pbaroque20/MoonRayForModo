"""Sampler change: real deadline, missing-page, cancellation and recovery checks."""
import argparse,json,traceback
from pathlib import Path
from native_build import build
from reference_runtime import sha,verify
from reference_repeatability import save,values,distance
from run_material_progressive import call
from run_m0 import guard
import asset_snapshot
HERE=Path(__file__).resolve().parent
p=argparse.ArgumentParser()
for n in ('source','runtime','ptx-build','baseline','output'):p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();src=a.source.resolve();rt=a.runtime.resolve();base=a.baseline.resolve();out=a.output.resolve();out.mkdir(exist_ok=False)
r={'status':'incomplete','scope':'changed sampler in complete vs suspended CPU/GPU jobs, 1/12 workers, forced texture misses, stale/corrupt continuation rejection, cancellation and recovery','cases':{},'native_image_abs':.002,'worker_count_identical':True}
try:
 guard();lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock)
 g=json.loads(a.ptx_build.read_text());ptx=Path(g['ptx']);assert sha(ptx)==g['build']['ptx_sha256']
 for n in ('gpu_trace.cu','gpu_jobs.h','texture_core.h','resume_core.h','surface_core.h','sample_stream.h','path_stage.h'):assert sha(HERE/n)==g['source_hashes'][str(HERE/n)]
 files=list(HERE.glob('*.h'))+[HERE/n for n in ('spatial_texture_probe.cc','run_sampling_recovery.py','native_build.py')];held={str(f):sha(f) for f in files};r['source_hashes']=held
 inc=[src/'toolchain/xpu/optix-dev/include',src/'toolchain/xpu/cuda_cudart-windows-x86_64-12.8.90-archive/include']
 exe,r['native_build']=build(src,HERE/'spatial_texture_probe.cc',out/'native',[rt/'libembree4.dll','-lcfgmgr32'],['-I'+str(v) for v in inc])
 for name in ('room-resident','room-close'):
  d=out/name;d.mkdir();s=asset_snapshot.verify(base/name/'grid-8/frozen/manifest.json')
  data=json.loads(call([exe,s,rt,ptx,d,s.parent/'assets'],rt,d,'probe',timeout=600));assert data['status']=='passed'
  control=values((d/'cpu-control.rgba').read_bytes());entry=r['cases'][name]={'probe':data,'image_errors':{}}
  for label in ('software','gpu-seeded-1','gpu-seeded-12','mixed-1','mixed-12','pressure','recovered'):
   delta=distance(control,values((d/(label+'.rgba')).read_bytes()));entry['image_errors'][label]=delta;assert delta<=.002,'Internal image divergence'
  assert (d/'gpu-seeded-1.rgba').read_bytes()==(d/'gpu-seeded-12.rgba').read_bytes(),'Worker count changed pixels'
  assert (d/'mixed-1.rgba').read_bytes()==(d/'mixed-12.rgba').read_bytes(),'Mixed worker count changed pixels'
  assert data['gpu-seeded-12']['gpu_samples']>0 and data['pressure']['texture_misses']>0
  assert data['cancel_safe'] and data['handoff_validation'] and data['malformed_result_invalidates_epoch']
  asset_snapshot.verify(s.parent/'manifest.json');save(out/'report.json',r);print(name,'recovery passed',entry['image_errors'],flush=True)
 assert all(sha(Path(k))==v for k,v in held.items());verify(rt,lock);guard();r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(out/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='passed')
