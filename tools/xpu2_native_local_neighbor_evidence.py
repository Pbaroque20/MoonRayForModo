"""Verify exact images, ownership and rotated timing for coordination changes."""
import hashlib,json,statistics,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
names=['xpu2-local-neighbor-'+n for n in ('controls','rough','adaptive','cancel','timing')]
reports={n:json.loads((ROOT/'test-results'/n/'report.json').read_text(encoding='utf-8')) for n in names}
checks=[];sentinels=[]
for name,r in reports.items():
 if r['status']!='passed' or r.get('error'):raise ValueError('Failed report '+name)
 cancel='round' not in r['runs'][0];prefix='image' if cancel else 'raw'
 folder=ROOT/'test-results'/name
 ref=folder/('reference' if cancel else '0-reference')
 refhash=[sha(ref/(prefix+'-'+c+'.pfm')) for c in ('rgb','alpha')]
 for row in r['runs']:
  if row['label']=='sentinel':
   if row['sentinel_comparison']['exactly_different_pixels']<10:raise ValueError('GPU sentinel absent')
   sentinels.append(dict(report=name,comparison=row['sentinel_comparison']));continue
  image=folder/(row['label'] if cancel else str(row['round'])+'-'+row['label'])
  hashes=[sha(image/(prefix+'-'+c+'.pfm')) for c in ('rgb','alpha')]
  if row['comparison']['status']!='passed' or row['comparison']['exactly_different_pixels'] or hashes!=refhash:raise ValueError('Exact image failure '+str(image))
  cq=row.get('coordination',[]);cq=cq if isinstance(cq,list) else [cq]
  if any(c['claimed']!=c['consumed'] for c in cq):raise ValueError('Claim ownership leak')
  checks.append(dict(report=name,label=row['label'],round=row.get('round'),raw_sha256=hashes,reference_sha256=refhash))
timing=reports['xpu2-local-neighbor-timing'];summary=timing['summary']
activity=[json.loads(line) for line in (ROOT/'test-results/xpu2-local-neighbor-activity.jsonl').read_text(encoding='utf-8').splitlines()]
owned={r['renderer_pid'] for r in timing['runs']}
allowed={str((ROOT/'test-results'/n/'moonray.exe').resolve()).lower() for n in ('xpu2-origin-build/control','xpu2-coordination-build/runtime','xpu2-local-neighbor-build/runtime')}
unexpected=[dict(utc=o['utc'],process=p) for o in activity for p in o['processes'] if p['ProcessId'] not in owned or (p['ExecutablePath'] and p['ExecutablePath'].lower() not in allowed)]
if unexpected:raise ValueError('Unexpected render activity')
metrics={}
for label in summary:
 rows=[r for r in timing['runs'] if r['round'] and r['label']==label]
 if label=='reference':continue
 metrics[label]={k:statistics.median(v) for k,v in {
  'inspected':[r['tiles']['inspected'] for r in rows],
  'local_claims':[r['tiles']['local'] for r in rows],
  'reordered':[r['tiles']['reordered'] for r in rows],
  'selection_seconds':[r['tiles']['selection_ns']/1e9 for r in rows],
  'gpu_lanes':[r['early']['gpu_lanes'] for r in rows],
  'waits':[r['early']['waits'] for r in rows],
  'submissions':[r['flight']['submitted'] for r in rows],
  'queue_full':[r['tiles']['queue_full'] for r in rows],
  'claimed':[r.get('coordination',{}).get('claimed',0) for r in rows],
  'kernel_seconds':[r['flight']['kernel_us']/1e6 for r in rows],
  'submit_seconds':[r['flight']['submit_ns']/1e9 for r in rows],
  'poll_seconds':[r['flight']['poll_ns']/1e9 for r in rows],
 }.items()}
# The frozen predecessor does not emit the new probe's claim profile.
metrics['previous']['claimed']=None
control=summary['control']['render_median'];reference=summary['reference']['render_median']
changes={label:dict(reduction_vs_control_percent=100*(control-summary[label]['render_median'])/control,slower_than_original_percent=100*(summary[label]['render_median']-reference)/reference) for label in ('neighbor','four')}
profiles={row['label']:row['integration'] for row in reports['xpu2-local-neighbor-controls']['runs'] if 'integration' in row}
build=json.loads((ROOT/'test-results/xpu2-local-neighbor-build/report.json').read_text(encoding='utf-8'))
for f,h in {**build['source_hashes'],**build['native_hashes']}.items():
 if sha(f)!=h:raise ValueError('Build source drift '+f)
unit=json.loads((ROOT/'test-results/xpu2-local-neighbor-unit/report.json').read_text(encoding='utf-8'))
if unit['status']!='passed' or unit['header_sha256']!=sha(ROOT/'xpu2/native_local_tile_policy.h') or unit['source_sha256']!=sha(ROOT/'xpu2/native_local_tile_policy_test.cc'):raise ValueError('Policy contract evidence drift')
result=dict(policy_contracts=unit,status='passed_exact_images',scope='Experimental one native render worker, RTX3090/AVX1 CPU. Bounded local-neighbor selection, four owned 64-ray chunks, combined coordination, two GPU flight slots. Native sampling, kernel and contribution order unchanged. No installed kit changes. Inclusive host timers do not measure isolated transfer bandwidth. Timing warmup excluded; three rotated rounds.',parent_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),collector_sha256=sha(__file__),exact_original_images=len(checks),intentional_gpu_sentinels=len(sentinels),performance=dict(summary=summary,metrics=metrics,changes=changes),profiles=profiles,profile_activity={row['label']:dict(before=row['activity_before'],after=row['activity_after'],timing_qualified=False) for row in reports['xpu2-local-neighbor-controls']['runs'] if 'integration' in row},raw_checks=checks,sentinels=sentinels,activity=dict(unexpected=unexpected,observations=activity),reports=reports,report_sha256={n:sha(ROOT/'test-results'/n/'report.json') for n in names},build=build)
(ROOT/'xpu2/native-local-neighbor-20261018.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
print(json.dumps({k:result[k] for k in ('status','exact_original_images','intentional_gpu_sentinels','performance')},indent=2))
