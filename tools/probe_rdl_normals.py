# python
"""Import authored point/corner normals into an isolated Modo scene and read maps back."""
import json,os,tempfile,traceback
from pathlib import Path
import lx,modo
from PySide2 import QtCore
from moonray_modo import rdl_import
out=Path(os.environ.get('MOONRAY_TEST_RESULTS',str(Path(tempfile.gettempdir())/'MoonRayForModo-tests')))/'rdl-normals';out.mkdir(parents=True,exist_ok=True)
result={'ok':False}
try:
 lx.eval('scene.new')
 verts=[[0,0,0],[1,0,0],[1,1,0],[0,1,0]];faces=[[0,1,2],[0,2,3]]
 normals={'point':[[0,0,1]]*4,'corner':[[0,0,1]]*3+[[0,1,0]]*3}
 data=dict(meshes=[dict(name=name,vertices=verts,faces=faces,uv=[],normals=values,tags=[None,None],subd=False,matrix=None,render=True,attributes=[]) for name,values in normals.items()],curves=[],instances=[],entities=[],materials={},cameras=[],settings={},links=[],warnings=[],source='test.rdla')
 result['import']=rdl_import.apply(data)
 for name,values in normals.items():
  item=next(i for i in modo.Scene().items('mesh') if i.name==name)
  geo=item.geometry;maps=geo.vmaps['RDL Normals'];assert len(maps)==1;nmap=maps[0]
  for f,face in enumerate(geo.polygons):
   for c,v in enumerate(face.vertices):
    actual=nmap.getNormal(v) if name=='point' else nmap.getNormal(v,face)
    expected=values[v.index] if name=='point' else values[f*3+c]
    assert all(abs(a-b)<1e-6 for a,b in zip(actual,expected)),(name,f,c,str(actual),expected)
 result['ok']=True
except Exception:result['error']=traceback.format_exc()
finally:
 (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
