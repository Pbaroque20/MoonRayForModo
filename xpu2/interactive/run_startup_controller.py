import json,time,subprocess,sys,statistics,traceback
from pathlib import Path
from reference_runtime import sha,verify
from reference_repeatability import save
from run_m0 import guard
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1];TR=ROOT/'test-results';OUT=TR/'interactive-startup-controller-20261022';OUT.mkdir(exist_ok=False);rt=TR/'interactive-reference-042';lock=HERE/'reference-lock.json';r={'status':'incomplete','scope':'fresh full-controller sessions with populated shader/OS caches; includes runtime and asset verification, read/admission, CPU/GPU setup, rendering, and image pipe','cases':{}}
try:
 guard();fixtures=json.loads((TR/'interactive-large-scenes-20261022/report.json').read_text());bench=json.loads((TR/'interactive-ray-hit-benchmark-20261022/report.json').read_text())
 configs={'baseline':(TR/'interactive-startup-before-20261022',TR/'interactive-prototype-build-20261022hits/build.json'),'candidate':(HERE,TR/'interactive-prototype-build-20261022startup/build.json')}
 save(OUT/'protocol.json',{'repetitions':3,'threads':12,'gate':'exact stored baseline RGBA; candidate median first image faster than baseline','cache':'populated shader cache; no OS cache purge; fresh process/controller each time','ordering':'alternate baseline/candidate'})
 for name,f in fixtures['cases'].items():
  c=r['cases'][name]={'baseline':[],'candidate':[]}
  for i in range(3):
   for label in (('baseline','candidate') if i%2==0 else ('candidate','baseline')):
    src,build=configs[label];d=OUT/(name+'-'+label+'-'+str(i));guard();cmd=[sys.executable,HERE/'startup_controller_probe.py','--source',src,'--build',build,'--manifest',Path(f['scenes']['8']).parent/'manifest.json','--output',d,'--runtime',rt,'--lock',lock]
    proc=subprocess.run(list(map(str,cmd)),cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=240,creationflags=subprocess.CREATE_NO_WINDOW);(OUT/(d.name+'.log')).write_text(proc.stdout+proc.stderr,encoding='utf-8');assert proc.returncode==0,proc.stdout[-1200:]+proc.stderr[-1200:]
    row=json.loads((d/'report.json').read_text());assert row['sha256']==bench['cases'][name]['native']['12']['runs'][0]['raw_sha256'];assert row['cpu_samples']==row['gpu_samples'] and row['migrated_paths']==0;c[label].append(row);save(OUT/'report.json',r);print(name,label,i,round(row['first_image_seconds'],3),round(row['final_image_seconds'],3),flush=True)
  c['median_first']={l:statistics.median(v['first_image_seconds'] for v in c[l]) for l in configs};c['median_final']={l:statistics.median(v['final_image_seconds'] for v in c[l]) for l in configs};assert c['median_first']['candidate']<c['median_first']['baseline'];save(OUT/'report.json',r)
 guard();verify(rt,json.loads(lock.read_text()));r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='passed')
