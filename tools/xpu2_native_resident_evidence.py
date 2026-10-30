"""Keep compact evidence for per-flight GPU resident records; no production qualification."""
import json,statistics,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from xpu2.reference import digest_file

def evidence():
 result={'schema':1,'scope':'One native worker, fixed sampling, selected diffuse shading; versioned per-flight GPU records, unchanged sampler math.','reports':{}}
 for name in ('contract-v2','checks','cancel','packet-checks','mixed-checks','timing'):
  path=ROOT/'test-results'/('xpu2-resident-'+name)/'report.json'
  r=json.loads(path.read_text());assert r['status']=='passed',(name,r.get('error'))
  rows=[]
  for v in r['runs']:
   row={k:v[k] for k in ('round','label','seconds','comparison','versus_fresh','activity_before','activity_after','prepared','resident','stdout','returncode') if k in v}
   if 'execution' in v:row['mcrt_seconds']=v['execution']['renderer_timings_seconds'].get('Mcrt time')
   if 'profiles' in v:row['profiles']={k:value for k,value in v['profiles'].items() if k in ('prepared','resident','gpu','work','transport','window','jobs','flight')}
   rows.append(row)
  result['reports'][name]={'sha256':digest_file(path),'runs':rows,'summary':r.get('summary',{})}
  if name=='timing':
   by={(v['round'],v['label']):v for v in r['runs'] if v['round']>0}
   rounds=sorted(set(n for n,label in by));result['comparisons']={}
   for a,b in (('resident','control'),('flush','control'),('resident','flush')):
    diff=[by[n,a]['execution']['renderer_timings_seconds']['Mcrt time']-by[n,b]['execution']['renderer_timings_seconds']['Mcrt time'] for n in rounds]
    result['comparisons'][a+'-'+b]={'paired_seconds':diff,'median_seconds':statistics.median(diff)}
 result['build_sha256']=digest_file(ROOT/'test-results/xpu2-resident-v2-build/report.json')
 result['failed_reports']={str(p.relative_to(ROOT)):digest_file(p) for p in (ROOT/'test-results/xpu2-resident-build/report.json',ROOT/'test-results/xpu2-resident-contract/report.json')}
 result['ptx_build_sha256']=digest_file(ROOT/'test-results/xpu2-resident-ptx/report.json')
 result['limitations']=['No scene-wide texture/material residency or native scene-index dispatch integration.','Flat input reconstruction, validation buffers and per-request allocations remain.','Resident tables are duplicated per flight to avoid cross-stream readers/writers.','Versioned descriptors add bytes; fewer repeated record uploads do not guarantee faster rendering.','No multiworker, arbitrary-material, adaptive or production-scene qualification.']
 return result
if __name__=='__main__':
 out=ROOT/'xpu2/native-resident-20261019.json';out.write_text(json.dumps(evidence(),indent=2)+'\n');print(out)
