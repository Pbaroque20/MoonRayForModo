"""Private sample-grid refinement; earlier quality targets stay frozen."""
import argparse,json,time,traceback
from pathlib import Path
import asset_snapshot
from run_speed_comparison import metric,timing
from reference_repeatability import values,run_reference,save
from reference_runtime import sha,verify
from run_material_progressive import call
from run_m0 import guard
HERE=Path(__file__).resolve().parent
p=argparse.ArgumentParser()
for n in ('runtime','build','speed-build','previous','output'):p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();rt=a.runtime.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False);old=json.loads(a.previous.read_text());root=a.previous.resolve().parent
protocol={'rule':'test increasing integer sample grids strictly between last failed and first successful coarse grids; stop at first passing grid; never change target error or correctness margins','repetitions':4,'discard_first':True,'postcheck_originals':4,'scope':'diagnostic, inherited reference gate failure remains open'}
save(out/'protocol.json',protocol);r={'status':'incomplete','protocol':protocol,'previous_sha256':sha(a.previous),'cases':{},'reference_repeatability_passed':old['reference_repeatability_passed'],'production_qualified':False}
try:
 assert old['status'] in ('passed','measured','partial') and 'error' not in old;build=json.loads(a.build.read_text());speed=json.loads(a.speed_build.read_text());exe,ptx,helper,bench=map(Path,(build['exe'],build['ptx'],build['helper'],speed['exe']))
 assert sha(bench)==speed['build']['executable_sha256'] and sha(ptx)==build['binary_hashes']['ptx'] and sha(exe)==build['binary_hashes']['exe'] and sha(helper)==build['asset_build']['executable_sha256']
 for k,v in speed['source_hashes'].items():assert sha(Path(k))==v
 lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);guard()
 for name,entry in old['cases'].items():
  ref=values((root/name/'converged-reference/beauty.rgba').read_bytes());r['cases'][name]={}
  for t in (1,12):
   source_case=entry['threads'][str(t)];case=r['cases'][name][str(t)]={'native':{},'target':source_case['frozen_target_error'],'quality_passed':source_case['high_spp_quality_passed']};winner=source_case['winner'];case['previous_selected']=winner
   if winner:
    failed=max(int(g) for g,d in source_case['native'].items() if int(g)<winner['grid'] and not d.get('meets_target_in_all_measured_runs',False))
    case['interval']=[failed,winner['grid']];case['selected_grid']=winner['grid'];case['selected_native']=source_case['native'][str(winner['grid'])]
    for grid in range(failed+1,winner['grid']):
     dest=out/f'{name}-t{t}-g{grid}';dest.mkdir();text=(root/name/'grid-8/input.rdla').read_text()+f'\nSceneVariables {{ ["pixel_samples"]={grid} }}\n';(dest/'input.rdla').write_text(text,encoding='utf-8')
     call([rt/'rdl2_convert.exe','-i',dest/'input.rdla','-o',dest/'input.rdlb'],rt,dest,'convert');asset_snapshot.freeze(dest/'input.rdlb',helper,rt,dest/'frozen',dest);scene=asset_snapshot.verify(dest/'frozen/manifest.json')
     guard();start=time.perf_counter();data=json.loads(call([bench,scene,rt,ptx,scene.parent/'assets',dest,t,4],rt,dest,'probe',timeout=600));data['process_wall_seconds']=time.perf_counter()-start;guard()
     assert data['status']=='passed' and data['workers_created']==t and data['steady_gpu_allocations']==data['steady_gpu_synchronizations']==0
     for row in data['runs']:row['error']=metric(values(Path(row['raw_file']).read_bytes()),ref,128,96);row['raw_sha256']=sha(Path(row['raw_file']))
     data['sampling_seconds']=timing(data['runs'][1:],'sampling_seconds');data['meets_target']=all(x['error']['relative_mse']<=case['target'] and x['error']['alpha']<=.015 for x in data['runs'][1:]);case['native'][str(grid)]=data
     print(name,t,grid,data['sampling_seconds']['median'],data['runs'][1]['error']['relative_mse'],data['meets_target'],flush=True);save(out/'report.json',r)
     if data['meets_target']:case['selected_grid']=grid;case['selected_native']=data;break
   case['reference_postcheck']=[]
   for i in range(4):
    v,row=run_reference(rt,root/name/'grid-8/frozen/scene.rdlb',out/f'{name}-t{t}-reference-{i}',t,exe,timeout=300);row['error']=metric(v,ref,128,96);case['reference_postcheck'].append(row)
   post=timing([x['stats'] for x in case['reference_postcheck'][1:]],'Mcrt time (s)');case['reference_post_sampling_seconds']=post;case['reference_original_sampling_seconds']=source_case['reference_sampling_seconds'];case['reference_drift_fraction']=post['median']/source_case['reference_sampling_seconds']['median']-1
   if winner:case['same_error_savings_vs_postcheck']=1-case['selected_native']['sampling_seconds']['median']/post['median']
   save(out/'report.json',r)
 verify(rt,lock);guard();r['measurement_status']='completed';r['status']='measured' if r['reference_repeatability_passed'] else 'partial'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(out/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(int(r.get('measurement_status')!='completed'))
