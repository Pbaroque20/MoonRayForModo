"""Interpret sampled per-active-lane costs without treating GPU service as frame time."""
import argparse,json,statistics
from pathlib import Path

def analyze(report,bridge):
 if report['status']!='passed':raise ValueError('Incomplete CPU qualification')
 result={'fixtures':{},'scope':'Exclusive elapsed time inside disjoint native CPU operations, sampled by SIMD call; includes preemption/internal waits, not hardware CPU-cycle attribution.'}
 for name in sorted({r['fixture'] for r in report['runs']}):
  runs=[r for r in report['runs'] if r['fixture']==name]
  times={r['label']:r['execution']['renderer_timings_seconds']['Mcrt time'] for r in runs}
  controls=[times[k] for k in ('off_before','off_after')];mean=statistics.mean(controls)
  sampled=[r for r in runs if r['rate']]
  if len(sampled)<2:raise ValueError('Need independent sampled controls')
  stages={}
  for stage in sampled[0]['cpu']:
   rows=[r['cpu'][stage] for r in sampled]
   if len({(r['calls'],r['lanes']) for r in rows})!=1:raise ValueError('Sample rate changed native work count')
   values=[r['ns_per_active_lane']/1000 for r in rows if r['ns_per_active_lane'] is not None]
   stages[stage]={'active_lanes':rows[0]['lanes'],'sampled_calls':[r['sampled_calls'] for r in rows],
    'us_per_active_lane':values,'mean_us_per_active_lane':statistics.mean(values) if values else None,
    'estimated_total_seconds':[r['estimated_total_seconds'] for r in rows],
    'above_1_5us_in_both_samples':bool(values) and min(values)>1.5}
  lighting=[]
  if 'all_lobes_mis' in stages:
   for row in sampled:
    cpu=row['cpu'];points=cpu['material_construct_maps']['lanes']
    seconds=sum(cpu[k]['estimated_total_seconds'] or 0 for k in ('all_lobes_mis','light_sample_eval','light_tree'))
    lighting.append(seconds*1e6/points if points else None)
  result['fixtures'][name]={'estimated_selected_lighting_us_per_material_point':lighting,
    'lighting_scope':'Sum of three disjoint sampled stages amortized over material shading points; includes multiple light samples per point. Excludes shadow tracing/visibility and is not a contiguous full-bounce measurement.',
    'mcrt_seconds':times,'sampling_overhead_fraction_vs_off_bracket':{r['label']:times[r['label']]/mean-1 for r in sampled},
    'off_bracket_spread_fraction':max(controls)/min(controls)-1,'compiled_candidate_off_vs_original_fraction':mean/times['reference']-1,'stages':stages}
 # Historic profiled bridge only: retain the accepted/used denominator and observer effect.
 e=bridge['exclusive'];accepted=bridge['gpu_work']['sampler_accepted_lanes'];light=bridge['gpu_work']['light_accepted_lanes']
 pipe=e['pipelines']['sampler_queue'];native=sum(sum(v for k,v in t['stages'].items() if k not in ('wait','native_shading','rejected_fallback','setup_cleanup','profiler_gpu_queries')) for t in e['host_threads'].values() if t['role']=='native_worker')
 result['bridge']={'sampler_used_lanes':accepted,'light_used_lanes':light,
  'light_queue_host_us_per_used_lane':e['pipelines']['light_queue']['exclusive_host_plumbing_seconds']*1e6/light,
  'light_gpu_service_us_per_used_lane':e['pipelines']['light_queue']['gpu_service_seconds']*1e6/light,
  'sampler_queue_host_us_per_used_lane':pipe['exclusive_host_plumbing_seconds']*1e6/accepted,
  'sampler_gpu_service_us_per_used_lane':pipe['gpu_service_seconds']*1e6/accepted,
  'sampler_plus_all_native_plumbing_serialized_us_per_used_lane':(pipe['exclusive_host_plumbing_seconds']+pipe['gpu_service_seconds']+native)*1e6/accepted,
  'all_pipelines_serialized_us_per_used_lane':e['amortized_costs']['serialized_host_plus_gpu_us_per_trip']*e['amortized_costs']['total_trips']/(accepted+light),
  'limitations':'The ~1.5us model charges all native admission/replay plumbing to sampler lanes but excludes the separate light queue. Host and GPU can overlap; original measurement added 14.7% frame time. These are planning scales, not a measured async critical-path break-even.'}
 result['unmeasured']=['Pure texture lookup cost separate from construction: material_construct_maps includes map evaluation and closure construction.','A whole bounce through the next trace: queues cross scope/thread/device boundaries; no exclusive per-bounce causal ledger was added.','Native multiworker scaling and enabled XPU2 speed on these heavier fixtures.']
 return result

def main():
 p=argparse.ArgumentParser();p.add_argument('report',type=Path);p.add_argument('bridge',type=Path);p.add_argument('output',type=Path);a=p.parse_args()
 value=analyze(json.loads(a.report.read_text()),json.loads(a.bridge.read_text()));a.output.write_text(json.dumps(value,indent=2)+'\n')
 print(json.dumps(value,indent=2))
if __name__=='__main__':main()
