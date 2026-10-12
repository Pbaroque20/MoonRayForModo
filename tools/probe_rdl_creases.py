# python
"""Read back imported hard edge/corner weights in an isolated Modo profile."""
import json,os,tempfile,traceback
from pathlib import Path
import lx,modo
from PySide2 import QtCore
from moonray_modo import rdl_import
out=Path(os.environ.get('MOONRAY_TEST_RESULTS',str(Path(tempfile.gettempdir())/'MoonRayForModo-tests')))/'rdl-creases';out.mkdir(parents=True,exist_ok=True)
result={'ok':False}
try:
 lx.eval('scene.new')
 record=dict(name='Creased RDL',vertices=[[0,0,0],[1,0,0],[1,1,0],[0,1,0]],faces=[[0,1,2,3]],uv=[],normals=[],tags=[None],subd=True,matrix=None,render=True,attributes=[],hard_edges=[[0,1]],hard_corners=[2])
 data=dict(meshes=[record],curves=[],instances=[],entities=[],materials={},cameras=[],settings={},links=[],warnings=[],source='test.rdla')
 result['import']=rdl_import.apply(data)
 item=next(i for i in modo.Scene().items('mesh') if i.name=='Creased RDL');geo=item.geometry;mesh=geo.internalMesh
 mapping=lx.object.MeshMap(mesh.MeshMapAccessor());mapping.SelectByName(lx.symbol.i_VMAP_SUBDIV,'Subdivision');mapid=mapping.ID()
 value=lx.object.storage('f',1)
 edge=lx.object.Edge(mesh.EdgeAccessor());edge.SelectEndpoints(geo.vertices[0]._id,geo.vertices[1]._id)
 assert edge.MapValue(mapid,value);assert abs(value.get()[0]-1)<1e-6
 point=lx.object.Point(mesh.PointAccessor());point.Select(geo.vertices[2]._id)
 assert point.MapValue(mapid,value);assert abs(value.get()[0]-1)<1e-6
 assert geo.polygons[0].accessor.Type()==lx.symbol.iPTYP_PSUB
 result.update(ok=True,edge_weight=1,corner_weight=1,catmull_clark=True)
except Exception:result['error']=traceback.format_exc()
finally:
 (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
