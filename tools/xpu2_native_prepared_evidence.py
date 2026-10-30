"""Keep compact evidence for early shared host records; no production qualification."""
import json,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from xpu2.reference import digest_file

def evidence():
 result={'schema':1,'scope':'One native worker, fixed sampling, selected diffuse shading; immutable host records, unchanged GPU ABI.','reports':{}}
 for name in ('contract','checks','cancel','packet-checks','timing'):
  path=ROOT/'test-results'/('xpu2-prepared-'+name)/'report.json'
  r=json.loads(path.read_text());assert r['status']=='passed',(name,r.get('error'))
  rows=[]
  for v in r['runs']:
   row={k:v[k] for k in ('round','label','seconds','comparison','versus_fresh','activity_before','activity_after','prepared','stdout','returncode') if k in v}
   if 'execution' in v:row['mcrt_seconds']=v['execution']['renderer_timings_seconds'].get('Mcrt time')
   if 'profiles' in v:row['profiles']={k:value for k,value in v['profiles'].items() if k in ('prepared','gpu','work','transport','window','jobs','flight')}
   rows.append(row)
  result['reports'][name]={'sha256':digest_file(path),'runs':rows,'summary':r.get('summary',{})}
  if name=='timing':
   by={(v['round'],v['label']):v for v in r['runs'] if v['round']>0}
   rounds=sorted(set(n for n,label in by));result['comparisons']={}
   for a,b in (('prepared','control'),('combined','control'),('combined','prepared')):
    diff=[by[n,a]['execution']['renderer_timings_seconds']['Mcrt time']-by[n,b]['execution']['renderer_timings_seconds']['Mcrt time'] for n in rounds]
    result['comparisons'][a+'-'+b]={'paired_seconds':diff,'median_seconds':statistics.median(diff)}
 result['build_sha256']=digest_file(ROOT/'test-results/xpu2-prepared-build/report.json')
 result['limitations']=['No GPU record residency, texture streaming, or native scene-index dispatch integration.','Request and window flat storage remains; no total peak-memory or request-allocation reduction claim.','Preparation byte counters are logical shared records versus equivalent flat records, not total copies or PCIe traffic.','Replay still reconstructs flat inputs for existing safety checks; worker reconstructs flat inputs before dispatch.','No multiworker, arbitrary-material, adaptive, production-scene or universal bitwise parity qualification.']
 return result
if __name__=='__main__':
 out=ROOT/'xpu2/native-prepared-20261019.json';out.write_text(json.dumps(evidence(),indent=2)+'\n');print(out)
