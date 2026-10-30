import json,traceback
from pathlib import Path
from reference_repeatability import save,values,distance
from run_material_progressive import call
from run_m0 import guard
HERE=Path(__file__).resolve().parent;TR=HERE.parents[1]/'test-results';OUT=TR/'interactive-ray-hit-images-shared-20261022';OUT.mkdir(exist_ok=False)
b=json.loads((TR/'interactive-ray-hit-shared-build-20261022/build.json').read_text());g=json.loads((TR/'interactive-ray-hit-shared-ptx-20261022/build.json').read_text());f=json.loads((TR/'interactive-large-scenes-20261022/report.json').read_text());rt=TR/'interactive-reference-042'
r={'status':'incomplete','bound':.002,'cases':{}}
try:
 for name,c in f['cases'].items():
  d=OUT/name;d.mkdir();scene=Path(c['scenes']['8']);rows={};r['cases'][name]=rows
  for mode in (0,1,2):
   out=d/str(mode);out.mkdir();guard();row=json.loads(call([b['exe'],scene,rt,g['ptx'],scene.parent/'assets',out,12,1,3,3034297317,1,33,mode],rt,out,'render',timeout=240));guard();rows[str(mode)]=row;save(OUT/'report.json',r)
  cpu=values(Path(rows['0']['runs'][0]['raw_file']).read_bytes())
  for mode in (1,2):
   v=values(Path(rows[str(mode)]['runs'][0]['raw_file']).read_bytes());rows[str(mode)]['max_delta']=distance(cpu,v);rows[str(mode)]['outliers']=[i for i in range(len(v)//4) if max(abs(v[i*4+k]-cpu[i*4+k]) for k in range(4))>.002]
   print(name,mode,rows[str(mode)]['max_delta'],len(rows[str(mode)]['outliers']),flush=True)
  save(OUT/'report.json',r)
 r['status']='measured'
except Exception as e:r.update(status='failed',error=str(e),traceback=traceback.format_exc())
save(OUT/'report.json',r);print(r['status'],r.get('error',''),flush=True)
