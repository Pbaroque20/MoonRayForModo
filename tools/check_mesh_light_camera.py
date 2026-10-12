"""Check native mesh-light camera modes without changing the installed kit."""
import argparse,json,subprocess,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import native,rdla
p=argparse.ArgumentParser();p.add_argument('runtime');p.add_argument('--output',default='test-results/mesh-light-camera');args=p.parse_args()
runtime=Path(args.runtime).resolve();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
results=[]
for mode,glow,surface in [('auto',1,False),('emitter',1,False),('surface',0,True),('hidden',0,False)]:
 scene={'camera':{'matrix':rdla.IDENTITY,'focal_mm':50,'film_mm':36},
  'meshes':[{'identity':'mesh','name':'Emitter','vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]],'material':''}],
  'entities':[{'identity':'emitter','name':'Emitter light','class':'MeshLight','parameters':{'geometry':'mesh','intensity':3,'visible_in_camera':1}}],
  'production':{'objects':{'mesh':{'mesh_camera_mode':mode}}}}
 path=out/(mode+'.rdla');path.write_text(rdla.scene_text(scene),encoding='utf-8')
 r=subprocess.run([str(runtime/'modo_rdl_import.exe'),str(path),str(runtime)],env=native.environment(runtime),capture_output=True,text=True,timeout=60)
 assert not r.returncode,r.stderr
 data=json.loads(r.stdout.rsplit('@@MODO_RDL_JSON',1)[1]);objects={v['name']:v for v in data['objects']}
 light=next(v['attributes'] for v in data['objects'] if v['type']=='MeshLight')
 mesh=objects['/modo/mesh/0']['attributes']
 assert light['visible_in_camera']==glow,(mode,light)
 assert mesh['visible_in_camera']==surface,(mode,mesh)
 assert light['intensity']==3 and light['on'],(mode,light)
 assert mesh['visible_shadow'],(mode,mesh)
 results.append({'mode':mode,'emitter_visible':glow,'surface_visible':surface,'illuminates':True})
(out/'report.json').write_text(json.dumps({'ok':True,'modes':results},indent=2),encoding='utf-8')
print('Native mesh-light camera modes: four passed')
