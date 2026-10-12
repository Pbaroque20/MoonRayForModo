"""Ask the native RDL reader to verify exported shape light/filter/shadow assignments."""
import argparse, json, subprocess, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import native, rdla
p=argparse.ArgumentParser();p.add_argument('runtime');p.add_argument('--output',default='test-results/rdl-link-roundtrip');args=p.parse_args()
runtime=Path(args.runtime).resolve();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
scene={'camera':{'matrix':rdla.IDENTITY,'focal_mm':50,'film_mm':36},'meshes':[],
 'entities':[
 {'identity':'shape','name':'Shape','class':'BoxGeometry','parameters':{}},
 {'identity':'target','name':'Target','class':'SphereGeometry','parameters':{}},
 {'identity':'light','name':'Light','class':'RectLight','parameters':{}},
 {'identity':'tint','name':'Tint','class':'IntensityLightFilter','parameters':{'color':[1,.5,.2]}}],
 'production':{'objects':{'shape':{'link_enabled':True,'lights':['light'],'shadow_exclude':['light'],'shadow_receivers':['target'],'light_filters':['tint']}}}}
path=out/'scene.rdla';path.write_text(rdla.scene_text(scene),encoding='utf-8')
r=subprocess.run([str(runtime/'modo_rdl_import.exe'),str(path),str(runtime)],env=native.environment(runtime),capture_output=True,text=True,timeout=60)
(out/'reader.log').write_text(r.stderr,encoding='utf-8')
if r.returncode:raise RuntimeError(r.stderr)
marker='@@MODO_RDL_JSON'
if marker not in r.stdout:raise RuntimeError('Native reader returned no scene document')
data=json.loads(r.stdout.rsplit(marker,1)[1]);(out/'readback.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
objects={v['name']:v for v in data['objects']}
layer=next(v['attributes'] for v in data['objects'] if v['type']=='Layer')
index=layer['geometries'].index('/modo/entity/shape')
for column,attribute,expected in (
 ('lightsets','lights','/modo/entity/light'),('shadowsets','lights','/modo/entity/light'),
 ('shadowreceiversets','geometries','/modo/entity/target'),('lightfiltersets','lightfilters','/modo/entity/tint')):
 reference=layer[column][index]
 assert objects[reference]['attributes'][attribute]==[expected],(column,objects[reference])
(out/'report.json').write_text(json.dumps({'ok':True,'checked':['lightsets','shadowsets','shadowreceiversets','lightfiltersets']},indent=2),encoding='utf-8')
print('Native RDL read-back: all four assignment sets passed')
