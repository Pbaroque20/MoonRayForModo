"""Retain exact-image, ownership and paired timing evidence for grouped replay."""
import argparse,json,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from xpu2.reference import digest_file
from xpu2_native_attribution_evidence import stages

def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('controls','timing','recovery','output'):p.add_argument('--'+n,type=Path,required=True)
 a=p.parse_args();result={'status':'passed','scope':'Single-worker reflection/transmission fixture; opt-in grouped replay, original GPU kernel and input comparisons.','reports':{},'timings':{},'paired':{}}
 for key in ('controls','timing','recovery'):
  file=getattr(a,key).resolve()/'report.json';r=json.loads(file.read_text())
  if r['status']!='passed' or r.get('image_mismatches'):raise ValueError('Unqualified '+key)
  rows=[]
  for v in r['runs']:
   if v['label']=='sentinel':
    if v['sentinel_comparison']['exactly_different_pixels']<10:raise ValueError('GPU sentinel not exercised')
   elif v['comparison']['status']!='passed' or v['comparison']['exactly_different_pixels']:raise ValueError('Image mismatch')
   row={k:v[k] for k in ('round','label','comparison','replay','seconds','versus_fresh') if k in v}
   if key=='timing':
    if v['activity_before'] or v['activity_after']:raise ValueError('Contaminated timing')
    stats=file.parent/(str(v['round'])+'-'+v['label'])/'stats.csv';row.update(mcrt=v['execution']['renderer_timings_seconds']['Mcrt time'],stages=stages(stats),stats_sha256=digest_file(stats))
   rows.append(row)
  result['reports'][key]={'path':str(file.relative_to(ROOT)),'sha256':digest_file(file),'runs':rows}
  if key=='timing':result['timings']=r['summary']
 rows=result['reports']['timing']['runs'];pairs={(v['round'],v['label']):v for v in rows};rounds=sorted({v['round'] for v in rows if v['round']>0})
 if len(rounds)<3 or len(pairs)!=len(rows):raise ValueError('Need unique rotated repetitions')
 for low,high in [('control','four'),('previous','control'),('reference','four')]:
  data={}
  for field in ('mcrt','integration','seconds'):
   def value(row):return row['stages']['Integration'] if field=='integration' else row[field]
   delta=[value(pairs[n,high])-value(pairs[n,low]) for n in rounds]
   data[field]={'per_round_seconds':delta,'median_seconds':statistics.median(delta)}
  result['paired'][high+'_minus_'+low]=data
 result['limitations']=['No installation or default change.','One native worker; not multiworker/production qualification.','Process checks cannot exclude brief intervening render activity.','Fewer queue locks does not eliminate duplicate sampler/packet preparation or broaden GPU shading coverage.','Cancellation check also exercises bounded neighbor selection; timings use FIFO.']
 a.output.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'timings':result['timings'],'paired':result['paired']},indent=2))
if __name__=='__main__':main()
