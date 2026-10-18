"""Collect pinned image, lifetime, phase-profile and paired timing evidence."""
import hashlib,json,re,statistics,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
names=['xpu2-integration-controls','xpu2-collect-controls','xpu2-collect-rough','xpu2-collect-adaptive','xpu2-collect-cancel64','xpu2-collect-cancel256','xpu2-collect-timing']
reports={name:json.loads((root/'test-results'/name/'report.json').read_text()) for name in names}
checks=[];sentinels=[]
for name,r in reports.items():
 if r['status']!='passed' or r.get('error'):raise ValueError('Failed report '+name)
 cancel='-cancel' in name;prefix='image' if cancel else 'raw'
 folder=root/'test-results'/name
 ref=folder/('reference' if cancel else '0-reference')
 refhash=[sha(ref/(prefix+'-'+c+'.pfm')) for c in ('rgb','alpha')]
 for row in r['runs']:
  if row['label']=='sentinel':
   if row['sentinel_comparison']['exactly_different_pixels']<10:raise ValueError('GPU sentinel absent')
   sentinels.append(dict(report=name,comparison=row['sentinel_comparison']));continue
  image=folder/(row['label'] if cancel else str(row['round'])+'-'+row['label'])
  hashes=[sha(image/(prefix+'-'+c+'.pfm')) for c in ('rgb','alpha')]
  if row['comparison']['status']!='passed' or row['comparison']['exactly_different_pixels'] or hashes!=refhash:raise ValueError('Exact original image failure '+str(image))
  checks.append(dict(report=name,label=row['label'],round=row.get('round'),raw_sha256=hashes,reference_sha256=refhash))
timing=reports['xpu2-collect-timing'];summary=timing['summary']
observations=[json.loads(line) for line in (root/'test-results/xpu2-collect-activity.jsonl').read_text().splitlines()]
owned={r['renderer_pid'] for r in timing['runs']}
allowed={str((root/'test-results'/p/'moonray.exe').resolve()).lower() for p in ('xpu2-origin-build/control','xpu2-chunk-build/runtime','xpu2-collect-build/runtime')}
unexpected=[dict(utc=o['utc'],process=p) for o in observations for p in o['processes'] if p['ProcessId'] not in owned or (p['ExecutablePath'] and p['ExecutablePath'].lower() not in allowed)]
if unexpected:raise ValueError('Competing render activity')
metrics={};breakdowns={};logs={}
for label in summary:
 rows=[r for r in timing['runs'] if r['round'] and r['label']==label]
 samples=[]
 for row in rows:
  path=root/'test-results/xpu2-collect-timing'/(str(row['round'])+'-'+label)/'render.log'
  text=path.read_text(errors='replace');logs[str(path)]=sha(path);values={}
  for key in ('Integration','Shading (excl. OIIO)','GPU intersection rays','GPU occlusion rays','[Total scalar time (excl. embree)]','[Total ISPC time (excl. embree)]'):
   match=re.search(r'\|\s*'+re.escape(key)+r'\s+([0-9.]+)\s+[0-9.]+%',text)
   if not match:raise ValueError('Missing category '+key)
   values[key]=float(match[1])
  samples.append(values)
 breakdowns[label]={k:statistics.median(v[k] for v in samples) for k in samples[0]}
 if label=='reference':continue
 metrics[label]={k:statistics.median(v) for k,v in {
  'gpu_lanes':[r['early']['gpu_lanes'] for r in rows],
  'waits':[r['early']['waits'] for r in rows],
  'submissions':[r['flight']['submitted'] for r in rows],
  'peak_inflight':[r['flight']['peak_inflight'] for r in rows],
  'queue_full':[r['tiles']['queue_full'] for r in rows],
  'kernel_seconds':[r['flight']['kernel_us']/1e6 for r in rows],
  'submit_seconds':[r['flight']['submit_ns']/1e9 for r in rows],
  'poll_seconds':[r['flight']['poll_ns']/1e9 for r in rows],
  'spin_ready':[r.get('collect',{}).get('spin_ready',0) for r in rows],
  'slept':[r.get('collect',{}).get('slept',0) for r in rows],
  'collect_polls':[r.get('collect',{}).get('polls',0) for r in rows],
 }.items()}
profiles={name:{r['label']:{k:dict(seconds=v['ns']/1e9,calls=v['calls']) for k,v in r['integration'].items()} for r in reports[name]['runs'] if 'integration' in r} for name in names[:2]}
ref=summary['reference']['render_median'];control=summary['control']['render_median']
changes={label:dict(reduction_vs_same_build_percent=100*(control-summary[label]['render_median'])/control,slower_than_original_percent=100*(summary[label]['render_median']-ref)/ref) for label in ('spin64','spin256')}
evidence=dict(status='passed_exact_images',scope='Experimental only. One render worker on RTX3090, AVX1 CPU. No install or production default change. Fine timers are inclusive and nested; separate from timing runs. Warmups excluded; three rotated repetitions. Spin can consume CPU otherwise available to other workers; multiworker scaling unqualified.',parent_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),collector_sha256=sha(Path(__file__)),exact_original_images=len(checks),intentional_gpu_sentinels=len(sentinels),performance=dict(summary=summary,metrics=metrics,native_time_breakdown_medians=breakdowns,changes=changes),inclusive_phase_profiles=profiles,raw_image_checks=checks,sentinels=sentinels,activity=dict(samples=len(observations),unexpected=unexpected,observations=observations),native_log_sha256=logs,reports=reports,report_sha256={name:sha(root/'test-results'/name/'report.json') for name in names},builds={name:json.loads((root/'test-results'/name/'report.json').read_text()) for name in ('xpu2-integration-build-v3','xpu2-collect-build')})
(root/'xpu2/native-integration-20261018.json').write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:evidence[k] for k in ('status','exact_original_images','intentional_gpu_sentinels','performance')},indent=2))
