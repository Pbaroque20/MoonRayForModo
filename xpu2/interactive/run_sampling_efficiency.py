"""Private fixed-target sampler ablation and matched-error timing; no qualification claim."""
import argparse,json,time,traceback,statistics
from pathlib import Path
import asset_snapshot
from run_speed_comparison import metric,quality,timing
from reference_repeatability import values,run_reference,save
from reference_runtime import sha,verify
from run_material_progressive import call
from run_m0 import guard
HERE=Path(__file__).resolve().parent
PLAN={'seeds':[None,17,47],'heldout_seeds':[101,151], 'coarse_grids':[4,6,8,10,12,14,17],
 'policies':{'0':'original Philox','1':'camera Sobol only','2':'first diffuse Sobol only','3':'both'},
 'quality_target':'unchanged per-fixture original 64spp relative MSE from prior report; minimum across worker counts',
 'selection':'first coarse grid whose three seeds meet frozen target; refine intervening integer grids',
 'high_spp_gate':{'max_pixel':.08,'max_block_mean':.015,'alpha':.015},
 'timing_repetitions':4,'discard_warmup':1,'threads':[1,12], 'native_policy':3,
 'native_timing':'same 2ms progressive pipeline, retained scene and pools; preparation separate',
 'qualification':'diagnostic only; original 12-worker repeatability remains open',
 'sampling':'four-dimensional Sobol with per-pixel Philox digital shift; later bounces retain Philox; not full Owen scrambling'}
def main():
 p=argparse.ArgumentParser()
 for n in ('runtime','build','ptx-build','previous','output'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--diagnostic',action='store_true')
 a=p.parse_args();rt=a.runtime.resolve();out=a.output.resolve();out.mkdir(exist_ok=False);save(out/'protocol.json',PLAN)
 old=json.loads(a.previous.read_text());root=a.previous.resolve().parent
 r={'status':'incomplete','protocol':PLAN,'cases':{},'production_qualified':False,'previous_sha256':sha(a.previous)}
 try:
  assert a.diagnostic,'Reference gate remains failed: explicit diagnostic admission required'
  lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);guard()
  b=json.loads(a.build.read_text());g=json.loads(a.ptx_build.read_text());assert b['status']==g['status']=='passed'
  bench=Path(b['exe']);ptx=Path(g['ptx']);assert sha(bench)==b['build']['executable_sha256'] and sha(ptx)==g['build']['ptx_sha256']
  # Decoder and asset helper are reused only for their unchanged file interfaces.
  helpers=json.loads((root.parent/'interactive-prototype-build-20261022c/build.json').read_text())
  decoder=Path(helpers['exe']);helper=Path(helpers['helper'])
  assert sha(decoder)==helpers['binary_hashes']['exe'] and sha(helper)==helpers['asset_build']['executable_sha256']
  held=dict(b['source_hashes']);held.update({str(HERE/n):sha(HERE/n) for n in ('run_sampling_efficiency.py','run_speed_comparison.py','reference_repeatability.py','asset_snapshot.py')})
  gpu_inputs=('gpu_trace.cu','gpu_jobs.h','texture_core.h','resume_core.h','surface_core.h','sample_stream.h','path_stage.h')
  for n in gpu_inputs:assert sha(HERE/n)==g['source_hashes'][str(HERE/n)],'GPU source drift'
  for k,v in held.items():assert sha(Path(k))==v,'CPU source drift'
  r.update(source_hashes=held,native_build_sha256=sha(a.build),gpu_build_sha256=sha(a.ptx_build),reference_identity=lock['identity'])
  for name,previous in old['cases'].items():
   folder=out/name;folder.mkdir();refpath=root/name/'converged-reference/beauty.rgba';ref=values(refpath.read_bytes())
   case=r['cases'][name]={'target':min(t['frozen_target_error'] for t in previous['threads'].values()),'reference_image_sha256':sha(refpath),'ablation':{},'search':{},'heldout':{},'timings':{}}
   scenes={}
   def scene(grid):
    if grid in scenes:return scenes[grid]
    existing=root/name/f'grid-{grid}/frozen/manifest.json'
    if existing.exists():v=asset_snapshot.verify(existing)
    else:
     d=folder/f'grid-{grid}';d.mkdir();text=(root/name/'grid-8/input.rdla').read_text()+f'\nSceneVariables {{ ["pixel_samples"]={grid} }}\n';source=d/'input.rdla';source.write_text(text,encoding='utf-8')
     call([rt/'rdl2_convert.exe','-i',source,'-o',d/'input.rdlb'],rt,d,'convert');asset_snapshot.freeze(d/'input.rdlb',helper,rt,d/'frozen',d);v=asset_snapshot.verify(d/'frozen/manifest.json')
    scenes[grid]=v;return v
   def native(label,grid,t=12,repeats=1,policy=3,seed=None):
    d=folder/label;d.mkdir();s=scene(grid);args=[bench,s,rt,ptx,s.parent/'assets',d,t,repeats,policy]
    if seed is not None:args.append(seed)
    guard();data=json.loads(call(args,rt,d,'native',timeout=600));guard()
    assert data['status']=='passed' and data['workers_created']==t and data['steady_gpu_allocations']==data['steady_gpu_synchronizations']==0
    for row in data['runs']:
     raw=Path(row['raw_file']);row['raw_sha256']=sha(raw);row['error']=metric(values(raw.read_bytes()),ref,128,96)
    data['sampling_seconds']=timing(data['runs'][1:] or data['runs'],'sampling_seconds')
    data['meets_target']=all(v['error']['relative_mse']<=case['target'] and v['error']['alpha']<=.015 for v in data['runs'])
    print(name,label,'spp',grid*grid,'seconds',round(data['sampling_seconds']['median'],4),'rMSE',round(data['runs'][-1]['error']['relative_mse'],8),'target',data['meets_target'],flush=True)
    return data
   for policy in range(4):case['ablation'][str(policy)]=native(f'ablation-{policy}',8,policy=policy);save(out/'report.json',r)
   case['high_spp']=[]
   for seed in PLAN['seeds']:
    data=native(f'high-{seed}',32,seed=seed);case['high_spp'].append(data);assert all(quality(v['error']) for v in data['runs']),'High-spp conformance failed';save(out/'report.json',r)
   def candidate(grid):
    rows=[native(f'search-g{grid}-seed{seed}',grid,seed=seed) for seed in PLAN['seeds']]
    good=all(d['meets_target'] for d in rows);case['search'][str(grid)]={'runs':rows,'passed':good};save(out/'report.json',r);return good
   failed=0;selected=None
   for grid in PLAN['coarse_grids']:
    if candidate(grid):selected=grid;break
    failed=grid
   if selected is None:raise RuntimeError('No native budget meets frozen target')
   for grid in range(failed+1,selected):
    if candidate(grid):selected=grid;break
   case['selected_grid']=selected;case['selected_spp']=selected*selected
   for seed in PLAN['heldout_seeds']:case['heldout'][str(seed)]=native(f'heldout-{seed}',selected,seed=seed)
   case['heldout_passed']=all(d['meets_target'] for d in case['heldout'].values());save(out/'report.json',r)
   # Recheck original before and after native timing, using four repetitions total.
   for t in PLAN['threads']:
    entry=case['timings'][str(t)]={'reference':[]};base_scene=scene(8)
    for i in range(2):
     pixels,row=run_reference(rt,base_scene,folder/f'xpu-t{t}-{i}',t,decoder,timeout=600);row['error']=metric(pixels,ref,128,96);entry['reference'].append(row)
    entry['native']=native(f'timed-t{t}',selected,t=t,repeats=4)
    for i in range(2,4):
     pixels,row=run_reference(rt,base_scene,folder/f'xpu-t{t}-{i}',t,decoder,timeout=600);row['error']=metric(pixels,ref,128,96);entry['reference'].append(row)
    entry['reference_sampling_seconds']=timing([x['stats'] for x in entry['reference'][1:]],'Mcrt time (s)')
    entry['savings']=1-entry['native']['sampling_seconds']['median']/entry['reference_sampling_seconds']['median'];save(out/'report.json',r)
   for s in scenes.values():asset_snapshot.verify(s.parent/'manifest.json')
  assert all(sha(Path(k))==v for k,v in held.items()),'Source drift during run';verify(rt,lock);guard()
  r['status']='partial';r['measurement_status']='completed';r['reason']='Reference repeatability qualification remains open; small fixture evidence only'
 except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
 save(out/'report.json',r);print(r['status'],r.get('error',''),flush=True);return int(r.get('measurement_status')!='completed')
if __name__=='__main__':raise SystemExit(main())
