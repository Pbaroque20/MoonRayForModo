"""Retain compact, provenance-linked evidence for the resident-record review fixes."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from xpu2.reference import digest_file

def evidence():
 result={'schema':1,'scope':'Resident-record safety/copy fixes, consolidated native build, true disabled baseline. Not full GPU material/path integration.','reports':{}}
 paths={'contract':'xpu2-resident-reviewed-contract','builder':'xpu2-resident-builder-audit','checks':'xpu2-resident-reviewed-checks','cancel':'xpu2-resident-reviewed-cancel','timing':'xpu2-resident-reviewed-timing','disabled':'xpu2-disabled-reviewed-baseline'}
 for name,folder in paths.items():
  path=ROOT/'test-results'/folder/'report.json';r=json.loads(path.read_text())
  if r['status'] not in ('passed','overhead_regression'):raise ValueError('Incomplete report '+name)
  rows=[]
  for run in r.get('runs',[]):
   row={k:run[k] for k in ('label','round','threads','seconds','comparison','resident_detail') if k in run}
   if 'execution' in run:row['mcrt_seconds']=run['execution']['renderer_timings_seconds']['Mcrt time']
   if 'profiles' in run:row['profiles']={k:run['profiles'][k] for k in ('resident','resident_detail','prepared','gpu','flight')}
   rows.append(row)
  result['reports'][name]={'path':str(path.relative_to(ROOT)),'sha256':digest_file(path),'status':r['status'],'summary':r.get('summary',{}),'runs':rows}
 result['build_sha256']=digest_file(ROOT/'test-results/xpu2-resident-reviewed-build/report.json')
 result['limitations']=['Current enabled images use one native worker and selected diffuse operations.','Disabled multiworker results include original-XPU nondeterminism and do not qualify enabled multiworker parity.','Resident-off control still performs experimental GPU shading.','Correctness fixes alone did not demonstrate a render-speed win.','Archived build stages remain available at their pinned Git revision; only the current resident shared build was rebuilt here.']
 return result

if __name__=='__main__':
 p=ROOT/'xpu2/resident-review-20261019.json';p.write_text(json.dumps(evidence(),indent=2)+'\n',encoding='utf-8');print(p)
