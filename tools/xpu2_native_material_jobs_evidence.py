"""Retain qualification and paired timings for bounded GPU material jobs."""
import json,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from xpu2.reference import digest_file

def main():
 folders=['checks','recovery-checks','cancel-retry','rough-transmission','mixed-larger','packet-bound','timing']
 result={'scope':'One native worker; existing diffuse sampling kernels with larger bounded multi-lobe submissions.','reports':{},'timings':{},'paired':{}}
 build=ROOT/'test-results/xpu2-material-jobs-build/report.json';bh=digest_file(build)
 result['build_report_sha256']=bh;result['exact_candidate_images']=0
 for name in folders:
  path=ROOT/('test-results/xpu2-material-jobs-'+name+'/report.json');r=json.loads(path.read_text())
  expected='incomplete' if name=='checks' else 'passed'
  if r['status']!=expected:raise ValueError('Unexpected report status '+name)
  if name=='checks' and r.get('error')!='Transport imbalance':raise ValueError('Unexpected initial failure')
  hashes=r.get('source_hashes',{})
  if r.get('build_sha256',hashes.get(str(build)))!=bh:raise ValueError('Different candidate '+name)
  rows=[]
  for v in r['runs']:
   c=v.get('comparison');label=v['label']
   if not c:raise ValueError('Missing comparison '+label)
   if label=='sentinel':
    if c['exactly_different_pixels']<10:raise ValueError('GPU sentinel absent')
   elif c['status']!='passed' or c['exactly_different_pixels']:raise ValueError('Image mismatch '+label)
   complete=name!='checks' or label=='reference' or 'profiles' in v
   if complete and label not in ('reference','sentinel'):result['exact_candidate_images']+=1
   profiles=v.get('profiles',{})
   row={k:v[k] for k in ('label','round','seconds','versus_fresh') if k in v}
   row.update(image_exact=c['exactly_different_pixels']==0,different_pixels=c['exactly_different_pixels'],profile_checks_completed=complete)
   row['mcrt']=v['execution']['renderer_timings_seconds'].get('Mcrt time')
   row['profiles']={k:profiles[k] for k in ('gpu','jobs','cpu_ahead','admission','window','tiles','flight','transport') if k in profiles}
   if name=='cancel-retry':row['recovery']={k:v[k] for k in ('flights','frames','jobs','light_queue','window') if k in v}
   if name=='timing' and (v['activity_before'] or v['activity_after']):raise ValueError('Timing contention')
   rows.append(row)
  result['reports'][name]={'path':str(path.relative_to(ROOT)),'sha256':digest_file(path),'status':r['status'],'error':r.get('error'),'runs':rows}
  if name=='timing':result['timings']=r['summary']
 rows=result['reports']['timing']['runs'];pairs={(v['round'],v['label']):v for v in rows}
 for high,low in [('two','control'),('two_shallow','control'),('two_shallow','two'),('two_shallow','reference')]:
  d=[pairs[n,high]['mcrt']-pairs[n,low]['mcrt'] for n in (1,2,3)]
  result['paired'][high+'_minus_'+low]={'seconds':d,'median_seconds':statistics.median(d)}
 result['preserved_cancellation_attempt']={'path':'test-results/xpu2-material-jobs-cancel/report.json','sha256':digest_file(ROOT/'test-results/xpu2-material-jobs-cancel/report.json'),'reason':'Harness still expected four chunks after configuration changed to two; stopped before cancellation.'}
 result['admission_baseline']={'path':'test-results/xpu2-material-admission-first/report.json','sha256':digest_file(ROOT/'test-results/xpu2-material-admission-first/report.json'),'note':'Earlier eight-case single-worker admission check; original probe predates failed-launch accounting correction.'}
 result['limitations']=['Not multiworker or production qualification.','No broader shader kernel, GPU texture lookup or complete GPU path integration.','Four-lobe cap only exercised with up to two eligible lobes in current fixtures.','No kit installation or default activation.','Before/after activity checks cannot exclude brief competing work between observations.']
 out=ROOT/'xpu2/native-material-jobs-20261019.json';out.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'exact_candidate_images':result['exact_candidate_images'],'timings':result['timings'],'paired':result['paired']},indent=2))
if __name__=='__main__':main()
