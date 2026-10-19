"""Retain exact-image, ownership and paired timing evidence for grouped native direct-light packets."""
import argparse,json,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_native_attribution_evidence import stages

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('controls','timing','recovery','output'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--supplemental',type=Path,nargs='*',default=[])
 a=p.parse_args();build_hash=None;result={'status':'passed','scope':'Single-worker grouped native direct-light packets; same native owner lifetime and accumulation order.','reports':{},'timings':{},'paired':{}}
 for key in ('controls','timing','recovery'):
  file=getattr(a,key).resolve()/'report.json';r=json.loads(file.read_text())
  if r['status']!='passed' or r.get('image_mismatches'):raise ValueError('Unqualified '+key)
  candidate=r.get('build_sha256') or next((h for f,h in r.get('source_hashes',{}).items() if Path(f).name=='report.json' and 'light-group' in f),None)
  if not candidate:raise ValueError('Missing frozen build identity')
  if build_hash is not None and candidate!=build_hash:raise ValueError('Mixed native builds')
  build_hash=candidate
  rows=[]
  for v in r['runs']:
   if v['label']=='sentinel':
    if v['sentinel_comparison']['exactly_different_pixels']<10:raise ValueError('GPU sentinel not exercised')
   elif v['comparison']['status']!='passed' or v['comparison']['exactly_different_pixels']:raise ValueError('Image mismatch')
   row={k:v[k] for k in ('round','label','comparison','sample_reuse','light_queue','light_group','sentinel_comparison','seconds','versus_fresh') if k in v}
   if key=='timing':
    if v['activity_before'] or v['activity_after']:raise ValueError('Contaminated timing')
    stats=file.parent/(str(v['round'])+'-'+v['label'])/'stats.csv';row.update(mcrt=v['execution']['renderer_timings_seconds']['Mcrt time'],stages=stages(stats),stats_sha256=digest_file(stats))
   rows.append(row)
  result['reports'][key]={'path':str(file.relative_to(ROOT)),'sha256':digest_file(file),'runs':rows}
  if key=='timing':result['timings']=r['summary']
 rows=result['reports']['timing']['runs'];pairs={(v['round'],v['label']):v for v in rows};rounds=sorted({v['round'] for v in rows if v['round']>0})
 if len(rounds)<3 or len(pairs)!=len(rows):raise ValueError('Need unique rotated repetitions')
 for low,high in [('control','four'),('reference','four')]:
  data={}
  for field in ('mcrt','integration','seconds'):
   def value(row):return row['stages']['Integration'] if field=='integration' else row[field]
   delta=[value(pairs[n,high])-value(pairs[n,low]) for n in rounds]
   data[field]={'per_round_seconds':delta,'median_seconds':statistics.median(delta)}
  result['paired'][high+'_minus_'+low]=data
 result['limitations']=['No installation or default change.','One native worker; not multiworker/production qualification.','Process checks cannot exclude brief intervening render activity.','Only supported primary fixed-sample, empty-AOV diffuse direct-light calculations are offloaded; native shadows and film remain unchanged.','Cancellation check also exercises bounded neighbor selection; timings use FIFO.']
 result['supplemental']=[]
 for folder in a.supplemental:
  file=folder.resolve()/'report.json';r=json.loads(file.read_text())
  if r['status']!='passed' or r.get('image_mismatches'):raise ValueError('Unqualified supplemental report')
  candidate=next((h for f,h in r.get('source_hashes',{}).items() if Path(f).name=='report.json' and 'light-group' in f),None)
  if candidate!=build_hash:raise ValueError('Mixed supplemental build')
  if any(v['comparison']['status']!='passed' or v['comparison']['exactly_different_pixels'] for v in r['runs']):raise ValueError('Supplemental image mismatch')
  result['supplemental'].append({'path':str(file.relative_to(ROOT)),'sha256':digest_file(file),'runs':[{k:v[k] for k in ('label','comparison','sample_reuse','light_queue') if k in v} for v in r['runs']]})
 for n in rounds:
  off,on=pairs[n,'control'],pairs[n,'four']
  if off.get('light_group') or not on.get('light_group'):raise ValueError('Incorrect grouping control')
  if on['light_queue']['submitted']>=off['light_queue']['submitted'] or on['light_queue']['gpu_used']!=off['light_queue']['gpu_used']:raise ValueError('Grouping coverage mismatch')
 result['build_report_sha256']=build_hash
 result['configuration_notes']=['control and four both enable sample reuse and direct-light offload; only four groups the light samples.','previous is the frozen async runtime with sample reuse and direct-light offload at their default off settings.','profile_four performs native numerical verification; timing four skips the replaced CPU calculation.']
 a.output.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'timings':result['timings'],'paired':result['paired']},indent=2))
if __name__=='__main__':main()
