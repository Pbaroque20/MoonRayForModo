"""Exclusive host stages and separate GPU service intervals; no cross-thread wall-time sum."""
import csv,json
from pathlib import Path

def read_csv(path):
 with path.open(newline="") as f:return list(csv.DictReader(f))

def analyze(folder,profiles):
 folder=Path(folder);threads={};totals={};calls={}
 clockRows=read_csv(folder/'exclusive.csv.clock.csv')
 if len(clockRows)!=1:raise ValueError('Missing profiler clock check')
 clock=clockRows[0];clock['relative_drift']=abs(int(clock['frame_ns'])/int(clock['steady_frame_ns'])-1)
 if clock['relative_drift']>.002:raise ValueError('Profiler clock drift exceeds 0.2%')
 for row in read_csv(folder/'exclusive.csv'):
  t=int(row['thread']);stage=row['stage'];ns=int(row['exclusive_ns']);n=int(row['calls'])
  if int(row['depth']) or int(row['errors']):raise ValueError('Unbalanced exclusive profiler')
  result=threads.setdefault(t,{'covered_seconds':int(row['covered_ns'])/1e9,'stages':{},'calls':{},'frame_scope_seconds':int(row['frame_ns'])/1e9})
  if stage in result['stages']:raise ValueError('Duplicate exclusive stage')
  result['stages'][stage]=ns/1e9;result['calls'][stage]=n
  totals[stage]=totals.get(stage,0)+ns/1e9;calls[stage]=calls.get(stage,0)+n
 for r in threads.values():
  if abs(sum(r['stages'].values())-r['covered_seconds'])>1e-8:raise ValueError('Exclusive stages do not partition covered host time')
  if r['covered_seconds']>r['frame_scope_seconds']+.001:raise ValueError('Host scope exceeds frame')
 gpu={};gpuTotals={'upload':0.,'kernel':0.,'readback':0.};trips=0
 for row in read_csv(folder/'exclusive.csv.gpu.csv'):
  count=int(row['trips'])
  if not count:continue
  key=int(row['track']);values={stage:float(row[stage+'_ms'])/1000 for stage in gpuTotals}
  if key in gpu:raise ValueError('GPU stream has more than one submitter')
  gpu[key]={'thread':int(row['thread']),'trips':count,**values};trips+=count
  for k,v in values.items():gpuTotals[k]+=v
 sampler=sum(r['trips'] for k,r in gpu.items() if k<2);light=sum(r['trips'] for k,r in gpu.items() if k>=2)
 if sampler!=profiles['flight']['retired'] or light!=profiles['light']['batches']:raise ValueError('Unaccounted GPU trips')
 excluded=('wait','native_shading','rejected_fallback','setup_cleanup','profiler_gpu_queries')
 plumbing=sum(v for k,v in totals.items() if k not in excluded)
 pipelines={}
 for t,r in threads.items():
  tracks=[k for k,v in gpu.items() if v['thread']==t]
  role=('sampler_queue' if max(tracks)<2 else 'light_queue') if tracks else ('native_worker' if r['stages'].get('native_shading',0)>0 else 'other_host')
  r['role']=role
  if tracks:
   count=sum(gpu[k]['trips'] for k in tracks);host=sum(v for k,v in r['stages'].items() if k not in excluded)
   service=sum(sum(gpu[k][stage] for stage in gpuTotals) for k in tracks)
   pipelines[role]={'trips':count,'exclusive_host_plumbing_seconds':host,'gpu_service_seconds':service,
     'host_plumbing_us_per_trip':host*1e6/count,'gpu_service_us_per_trip':service*1e6/count}

 return {'status':'passed','clock_check':clock,'host_threads':threads,'host_exclusive_seconds_summed_across_threads':totals,'host_stage_calls':calls,
  'gpu_service_seconds_summed_across_streams':gpuTotals,'gpu_streams':gpu,'pipelines':pipelines,'sampler_trips':sampler,'light_trips':light,
  'amortized_costs':{'total_trips':trips,'host_plumbing_wall_us_per_trip':plumbing*1e6/trips,'setup_cleanup_seconds':totals.get('setup_cleanup',0),
   'serialized_host_plus_gpu_us_per_trip':(plumbing+sum(gpuTotals.values()))*1e6/trips},
  'limitations':['Host times are exclusive wall time per thread, including mutex blocking/preemption; they are not CPU-cycle measurements.',
   'Do not add host threads, CPU waits or GPU streams to reconstruct frame elapsed time.',
   'GPU event stages exclude each other within a trip, but can overlap other streams and include device scheduling delay.',
   'Serialized cost per trip is a non-overlapped cost model, not the observed critical path or a guaranteed break-even threshold.',
   'Native work outside marked functions remains unattributed; original OptiX intersection activity is not GPU shading work.']}
