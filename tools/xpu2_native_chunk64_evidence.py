import json,hashlib,statistics,subprocess,re
from pathlib import Path
root=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
names=['xpu2-chunk64-controls','xpu2-chunk64-rough','xpu2-chunk64-adaptive','xpu2-chunk64-cancel','xpu2-chunk64-timing']
reports={n:json.loads((root/'test-results'/n/'report.json').read_text()) for n in names}
for n,r in reports.items():
 if r.get('error') or (r['status']!='passed' and not(n.endswith('timing') and r['status']=='image_differences')):raise ValueError('Validation failed '+n)
rows=[];hash_checks=[];contrasts=[]
for n,r in reports.items():
 folder=root/'test-results'/n
 cancel=n.endswith('cancel');prefix='image' if cancel else 'raw'
 baseline=folder/('reference' if cancel else '0-reference')
 reference_hashes=[sha(baseline/(prefix+'-'+c+'.pfm')) for c in ('rgb','alpha')]
 for row in r['runs']:
  label=row['label']
  if label=='sentinel':continue
  rows.append((n,row))
  image=folder/(label if cancel else str(row['round'])+'-'+label)
  hashes=[sha(image/(prefix+'-'+c+'.pfm')) for c in ('rgb','alpha')]
  item=dict(report=n,round=row.get('round'),label=label,rgba_files_exact=hashes==reference_hashes,raw_sha256=hashes,reference_sha256=reference_hashes)
  if label=='chunk128':
   if row['comparison']['status']!='passed' or row['comparison']['exactly_different_pixels']!=5:raise ValueError('128-ray contrast changed')
   contrasts.append(item)
  else:
   if row['comparison']['status']!='passed' or row['comparison']['exactly_different_pixels'] or not item['rgba_files_exact']:raise ValueError('Strict original RGBA match failed '+n+' '+label)
   hash_checks.append(item)
timing=reports['xpu2-chunk64-timing'];observations=[json.loads(l) for l in (root/'test-results/xpu2-chunk64-activity.jsonl').read_text().splitlines()]
owned={x['renderer_pid'] for x in timing['runs']}
allowed={str((root/p/'moonray.exe').resolve()).lower() for p in ('test-results/xpu2-origin-build/control','test-results/xpu2-window-build/runtime','test-results/xpu2-chunk-build/runtime')}
unexpected=[dict(utc=o['utc'],process=p) for o in observations for p in o['processes'] if p['ProcessId'] not in owned or (p['ExecutablePath'] and p['ExecutablePath'].lower() not in allowed)]
if unexpected:raise ValueError('Competing renderer '+str(unexpected))
summary=timing['summary'];ref=summary['reference']['render_median'];prev=summary['previous']['render_median'];control=summary['control']['render_median'];candidate=summary['eight']['render_median'];larger=summary['chunk128']['render_median']
metrics={}
for label in summary:
 group=[x for x in timing['runs'] if x['round'] and x['label']==label]
 if label=='reference':continue
 metrics[label]={k:statistics.median(v) for k,v in {
 'submissions':[x['flight']['submitted'] for x in group],
 'peak_inflight':[x['flight']['peak_inflight'] for x in group],
 'max_queue':[x['tiles']['max_queue'] for x in group],
 'queue_full':[x['tiles']['queue_full'] for x in group],
 'gpu_lanes':[x['early']['gpu_lanes'] for x in group],
 'waits':[x['early']['waits'] for x in group],
 'ready_fraction':[x['window']['ready_at_replay']/x['window']['reused'] for x in group],
 'kernel_seconds':[x['flight']['kernel_us']/1e6 for x in group],
 'submit_seconds':[x['flight']['submit_ns']/1e9 for x in group],
 'poll_seconds':[x['flight']['poll_ns']/1e9 for x in group],
 }.items()}
breakdowns={};breakdown_hashes={}
for label in summary:
 samples=[]
 for x in timing['runs']:
  if x['round']==0 or x['label']!=label:continue
  logfile=root/'test-results/xpu2-chunk64-timing'/(str(x['round'])+'-'+label)/'render.log'
  lines=logfile.read_text(errors='replace');breakdown_hashes[str(logfile)]=sha(logfile)
  values={}
  for key in ('Integration','Shading (excl. OIIO)','GPU intersection rays','GPU occlusion rays','[Total scalar time (excl. embree)]','[Total ISPC time (excl. embree)]'):
   match=re.search(r'\|\s*'+re.escape(key)+r'\s+([0-9.]+)\s+[0-9.]+%',lines)
   if not match:raise ValueError('Missing native time category '+key)
   values[key]=float(match[1])
  samples.append(values)
 breakdowns[label]={key:statistics.median(x[key] for x in samples) for key in samples[0]}
evidence=dict(collector_sha256=sha(Path(__file__)),status='passed_64_ray_candidate_with_separate_128_ray_roundoff_contrast',scope='One CPU worker, RTX3090, unchanged isolated runtime/PTX. No installation. All 64-ray/control images must match original XPU samples and float32-file hashes exactly; known 128-ray contrast remains separately marked image_differences.',parent_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True,cwd=root).strip(),ordinary_images=len(rows),exact_original_images=len(hash_checks),separate_128_ray_contrasts=len(contrasts),intentional_gpu_sentinels=sum(x['label']=='sentinel' for r in reports.values() for x in r['runs']),performance=dict(summary=summary,metrics=metrics,native_time_breakdown_medians=breakdowns,native_log_sha256=breakdown_hashes,reduction_vs_previous_percent=100*(prev-candidate)/prev,reduction_vs_same_build_four_percent=100*(control-candidate)/control,reduction_vs_128_ray_eight_percent=100*(larger-candidate)/larger,slower_than_xpu_percent=100*(candidate-ref)/ref),raw_image_checks=hash_checks,contrast_checks=contrasts,activity=dict(samples=len(observations),unexpected=unexpected,observations=observations),reports=reports,report_sha256={n:sha(root/'test-results'/n/'report.json') for n in names},build_report_sha256=sha(root/'test-results/xpu2-chunk-build/report.json'),build=json.loads((root/'test-results/xpu2-chunk-build/report.json').read_text()))
(root/'xpu2/native-chunk64-20261018.json').write_text(json.dumps(evidence,indent=2)+'\n')
print(json.dumps({k:v for k,v in evidence.items() if k in ('status','ordinary_images','exact_original_images','separate_128_ray_contrasts','intentional_gpu_sentinels','performance')},indent=2))
