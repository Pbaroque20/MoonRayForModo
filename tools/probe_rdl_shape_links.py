# python
"""Check native shape light/shadow links in an isolated Modo scene."""
import json,os,tempfile,traceback
from pathlib import Path
import lx,modo
from PySide2 import QtCore
from moonray_modo import rdl_import,properties
out=Path(os.environ.get('MOONRAY_TEST_RESULTS',str(Path(tempfile.gettempdir())/'MoonRayForModo-tests')))/'rdl-shape-links';out.mkdir(parents=True,exist_ok=True)
result={'ok':False}
try:
 lx.eval('scene.new')
 geometry={'vertex_list_0':[[0,0,0],[1,0,0],[0,1,0]],'face_vertex_count':[3],'vertices_by_index':[0,1,2]}
 source={'version':1,'objects':[
 {'name':'vars','type':'SceneVariables','attributes':{'layer':'layer'}},
 {'name':'layer','type':'Layer','attributes':{'geometries':['receiver','emitterMesh'],'parts':['',''],'surface_shaders':['paint',None],'lightsets':['onlyEmitter',None],'shadowsets':['noEmitterShadow',None]}},
 {'name':'receiver','type':'BoxGeometry','attributes':{'size':[1,1,1]}},
 {'name':'emitterMesh','type':'RdlMeshGeometry','attributes':geometry},
 {'name':'emitter','type':'MeshLight','attributes':{'geometry':'emitterMesh'}},
 {'name':'paint','type':'DwaBaseMaterial','attributes':{}},
 {'name':'other','type':'RectLight','attributes':{}},
 {'name':'onlyEmitter','type':'LightSet','attributes':{'lights':['emitter']}},
 {'name':'noEmitterShadow','type':'ShadowSet','attributes':{'lights':['emitter']}}]}
 plan=rdl_import.plan(source,'test.rdla');link=next(v for v in plan['links'] if v['shadows'])
 result['import']=rdl_import.apply(plan)
 meshes={m.name:m for m in modo.Scene().items()}
 held=properties.scene_settings()['production']['objects'][meshes[link['geometry']].id]
 emitter_id=meshes[link['lights'][0]].id
 assert held['link_enabled'] and held['lights']==[emitter_id] and held['shadow_exclude']==[emitter_id],held
 light=next(i for i in modo.Scene().items() if i.type=='moonray.MeshLight')
 assert light.channel('mr_geometry').get()==emitter_id,'Emitter geometry reference lost'
 assert 'is left out' not in result['import'],result['import']
 result.update(ok=True,emitter_id=emitter_id,links=held)
except Exception:result['error']=traceback.format_exc()
finally:
 (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
