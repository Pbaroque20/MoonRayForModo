# python
"""Import nested instancers whose materials and lighting come from their outer owners."""
import json, os, tempfile, traceback
from pathlib import Path
import lx, modo
from PySide2 import QtCore
from moonray_modo import rdl_import, host, rdla
out=Path(os.environ.get('MOONRAY_TEST_RESULTS',str(Path(tempfile.gettempdir())/'MoonRayForModo-tests')))/'rdl-nested-links'
out.mkdir(parents=True,exist_ok=True);result={'ok':False}
try:
 lx.eval('scene.new')
 source={'version':1,'objects':[
 {'name':'vars','type':'SceneVariables','attributes':{'layer':'layer'}},
 {'name':'layer','type':'Layer','attributes':{'geometries':['one','two'],'parts':['',''],
  'surface_shaders':['paint','paint'],'lightsets':['keyOnly','fillOnly'],'shadowsets':['noFill',None],
  'lightfiltersets':['filters',None]}},
 {'name':'mesh','type':'RdlMeshGeometry','attributes':{'vertex_list_0':[[0,0,0],[1,0,0],[1,1,0],[0,1,0]],
  'face_vertex_count':[3,3],'vertices_by_index':[0,1,2,0,2,3],
  'part_list':['left','right'],'part_face_count_list':[1,1],'part_face_indices':[0,1]}},
 {'name':'paint','type':'DwaBaseMaterial','attributes':{}},
 {'name':'key','type':'RectLight','attributes':{}}, {'name':'fill','type':'SphereLight','attributes':{}},
 {'name':'keyOnly','type':'LightSet','attributes':{'lights':['key']}},
 {'name':'fillOnly','type':'LightSet','attributes':{'lights':['fill']}},
 {'name':'noFill','type':'ShadowSet','attributes':{'lights':['fill']}},
 {'name':'tint','type':'IntensityLightFilter','attributes':{'color':[1,.5,.2]}},
 {'name':'filters','type':'LightFilterSet','attributes':{'lightfilters':['tint']}}]}
 source['objects'] += [{'name':name,'type':'RdlInstancerGeometry','attributes':{'method':2,'references':['inner'],'xform_list':[rdl_import.IDENTITY]*2}} for name in ('one','two')]
 source['objects'].append({'name':'inner','type':'RdlInstancerGeometry','attributes':{'method':2,'references':['mesh'],'xform_list':[rdl_import.IDENTITY]*2}})
 plan=rdl_import.plan(source,'test.rdla');result['import']=rdl_import.apply(plan)
 assert 'geometry is unavailable' not in result['import'],result['import']
 mesh=next(m for m in modo.Scene().items('mesh') if m.name==plan['meshes'][0]['name'])
 assert len(plan['meshes'])==2 and len(plan['instances'])==6,plan
 assert len(list(modo.Scene().items('meshInst')))==6,'Instances expanded'
 assert len(mesh.geometry.vertices)==4 and len(mesh.geometry.polygons)==2,'Topology changed'
 result['captures']=[]
 for evaluated in (False,True):
  snap=host.snapshot(evaluated_geometry=evaluated)
  linked={tag:value['rdl_layer_links'] for tag,value in snap['materials'].items() if value.get('rdl_layer_links')}
  assert len(linked)==2,linked
  assert len({tuple(v['lights']) for v in linked.values()})==2,linked
  assert sum(bool(v.get('light_filters')) for v in linked.values())==1,linked
  path=out/('evaluated.rdla' if evaluated else 'direct.rdla');path.write_text(rdla.scene_text(snap),encoding='utf-8')
  result['captures'].append({'evaluated':evaluated,'links':linked,'path':str(path)})
 result['ok']=True
except Exception:result['error']=traceback.format_exc()
finally:
 (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
