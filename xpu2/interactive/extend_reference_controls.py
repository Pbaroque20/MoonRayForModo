"""Predeclared larger twelve-worker reference-only control set; no adaptive retry."""
import argparse,json,hashlib,traceback
from pathlib import Path
from reference_repeatability import run_reference,values,envelope,against,save
from reference_runtime import verify,sha
from run_m0 import guard
HERE=Path(__file__).resolve().parent
p=argparse.ArgumentParser()
for n in ('runtime','build','scene','previous','output'):p.add_argument('--'+n,type=Path,required=True)
a=p.parse_args();rt=a.runtime.resolve();scene=a.scene.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
plan={'threads':[12],'new_standalone_calibration':48,'heldout_originals':24,'fallbacks':8,'rule':'unchanged measured sup-norm envelope, no epsilon or post-holdout tuning','include_previous':'standalone calibration and held-out originals only; previous failed fallback excluded','purpose':'sample rare twelve-thread original variation after the initial calibration missed it; finite scope only'}
save(out/'protocol.json',plan);r={'status':'incomplete','protocol':plan,'cases':{}}
try:
 lock=json.loads((HERE/'reference-lock.json').read_text());verify(rt,lock);guard();build=json.loads(a.build.read_text());exe=Path(build['exe']);assert sha(exe)==build['binary_hashes']['exe']
 previous=json.loads(a.previous.read_text());assert previous['scene_sha256']==sha(scene);r['scene_sha256']=sha(scene);r['previous_sha256']=sha(a.previous);r['runtime_identity']=lock['identity'];r['cases']['1']=previous['cases']['1'];assert all(x['passed'] for k in ('heldout','fallback') for x in r['cases']['1'][k])
 controls=[];case=r['cases']['12']={'calibration':[],'heldout':[],'fallback':[]}
 for row in previous['cases']['12']['calibration']+previous['cases']['12']['heldout']:
  folder=Path(row['folder']);controls.append(values((folder/'beauty.rgba').read_bytes()));case['calibration'].append(dict(row,historical=True))
 for i in range(plan['new_standalone_calibration']):
  v,row=run_reference(rt,scene,out/f'cal-{i}',12,exe);controls.append(v);case['calibration'].append(row);save(out/'report.json',r);print('cal',i,row['raw_sha256'][:8],flush=True)
 case['frozen_bound']=envelope(controls);save(out/'frozen-envelope.json',case);print('FROZEN',case['frozen_bound'],flush=True)
 passed=True
 for phase,count in [('heldout',plan['heldout_originals']),('fallback',plan['fallbacks'])]:
  for i in range(count):
   v,row=run_reference(rt,scene,out/f'{phase}-{i}',12,exe,fallback=phase=='fallback');row.update(against(v,controls,case['frozen_bound']));case[phase].append(row);passed &= row['passed'];save(out/'report.json',r);print(phase,i,row['max_distance_to_controls'],row['passed'],flush=True)
 verify(rt,lock);guard();r['status']='passed' if passed else 'failed';r['global_bit_exact_claim']=False
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(out/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(int(r['status']!='passed'))
