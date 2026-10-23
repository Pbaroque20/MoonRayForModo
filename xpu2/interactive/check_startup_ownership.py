import json,traceback
from pathlib import Path
from reference_runtime import sha
from reference_repeatability import save
from run_material_progressive import call
from run_m0 import guard
HERE=Path(__file__).resolve().parent;TR=HERE.parents[1]/'test-results';OUT=TR/'interactive-startup-ownership-20261022';OUT.mkdir(exist_ok=False);rt=TR/'interactive-reference-042';b=json.loads((TR/'interactive-startup-candidate-build-20261022/build.json').read_text());g=json.loads((TR/'interactive-startup-material-ptx-20261022/build.json').read_text());old=json.loads((TR/'interactive-ray-hit-images-shared-20261022/report.json').read_text());fixtures=json.loads((TR/'interactive-large-scenes-20261022/report.json').read_text());r={'status':'incomplete','cases':{}}
try:
 for name,f in fixtures['cases'].items():
  r['cases'][name]={};scene=Path(f['scenes']['8'])
  for mode in (0,1):
   d=OUT/(name+'-'+str(mode));d.mkdir();guard();row=json.loads(call([b['exe'],scene,rt,g['ptx'],scene.parent/'assets',d,12,1,3,3034297317,1,33,mode],rt,d,'native',timeout=120));raw=Path(row['runs'][0]['raw_file']);previous=Path(old['cases'][name][str(mode)]['runs'][0]['raw_file']);assert raw.read_bytes()==previous.read_bytes();r['cases'][name][str(mode)]={'sha256':sha(raw),'baseline_sha256':sha(previous),'byte_identical':True};save(OUT/'report.json',r);print(name,mode,'exact ownership image',flush=True)
 guard();r['status']='passed'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True);raise SystemExit(r['status']!='passed')
