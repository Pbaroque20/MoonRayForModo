"""Retain compact, reproducible overhead and shared-record measurements."""
import json, statistics, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from xpu2.reference import digest_file

def evidence():
 result={'schema':1,'scope':'One native worker; selected diffuse material operations; original XPU unchanged.','reports':{},'comparisons':{},'scopes':{}}
 for name in ('overhead-checks','overhead-timing','data-layers-checks','data-layers-timing'):
  path=ROOT/'test-results'/('xpu2-'+name)/'report.json'
  r=json.loads(path.read_text());assert r['status']=='passed',(name,r.get('error'))
  rows=[]
  for v in r['runs']:
   rows.append({k:v[k] for k in ('round','label','seconds','comparison')})
   rows[-1]['mcrt_seconds']=v['execution']['renderer_timings_seconds']['Mcrt time']
   rows[-1]['activity_before']=v['activity_before'];rows[-1]['activity_after']=v['activity_after']
   if 'profiles' in v: rows[-1]['profiles']={k:value for k,value in v['profiles'].items() if k in ('overhead','work','flight','gpu','transport','window','jobs','scheduled_upload_bytes','scheduled_payload_bytes')}
  result['reports'][name]={'sha256':digest_file(path),'runs':rows,'summary':r.get('summary',{})}
  if name.endswith('timing'):
   labels=sorted(set(v['label'] for v in r['runs']))
   for label in labels:
    measured=[v for v in r['runs'] if v['label']==label and v['round']>0]
    if measured and 'overhead' in measured[0].get('profiles',{}):
     result['scopes'][label]={key:{'median_seconds':statistics.median(v['profiles']['overhead'][key]['ns']/1e9 for v in measured),'median_calls':statistics.median(v['profiles']['overhead'][key]['calls'] for v in measured)} for key in measured[0]['profiles']['overhead']}
   pairs=(('control','previous'),('profile','control')) if name=='overhead-timing' else (('layered','control'),)
   for a,b in pairs:
    by={(v['round'],v['label']):v for v in r['runs'] if v['round']>0}
    rounds=sorted(set(n for n,label in by))
    diffs=[by[n,a]['execution']['renderer_timings_seconds']['Mcrt time']-by[n,b]['execution']['renderer_timings_seconds']['Mcrt time'] for n in rounds]
    result['comparisons'][name+':'+a+'-'+b]={'paired_seconds':diffs,'median_seconds':statistics.median(diffs)}
 result['build_sha256']=digest_file(ROOT/'test-results/xpu2-overhead-v2-build/report.json')
 result['failed_build_sha256']=digest_file(ROOT/'test-results/xpu2-overhead-build/report.json')
 result['limitations']=['Scope times overlap and are not additive frame costs.','Opt-in nanosecond scopes perturb scheduling; compare profile-on and profile-off timing.','Allocation scopes exclude destruction. Queue-lock scopes cover public submit paths, not all window locks.','CUDA API scopes measure host-call duration, not PCIe transfer duration or exclusive device computation.','Shared records are rebuilt within each batch; scene-wide GPU residency and dependency-index integration are not implemented by this test.','No multiworker, arbitrary-material, production-scene or full-parity claim.']
 return result
if __name__=='__main__':
 out=ROOT/'xpu2/native-overhead-20261019.json';out.write_text(json.dumps(evidence(),indent=2)+'\n');print(out)
