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
 data=dict(meshes=[dict(name=name,vertices=verts,faces=faces,uv=[[0,0],[1,0],[1,1],[.2,.3],[.8,.9],[0,1]],normals=values,tags=[None,None],subd=False,matrix=None,render=True,attributes=[]) for name,values in normals.items()],curves=[],instances=[],entities=[],materials={},cameras=[],settings={},links=[],warnings=[],source='test.rdla')
 shear=[1,1,0,0,0,1,0,0,0,0,1,0,2,0,0,1]
 mirror=[-1,0,0,0,0,1,0,0,0,0,1,0,2,0,0,1]
 originals=list(data['meshes'])
 for suffix,matrix in [(' sheared',shear),(' mirrored',mirror)]:
  for record in originals:
   baked=dict(record,name=record['name']+suffix,matrix=matrix)
   data['meshes'].append(baked)
   normals[baked['name']]=rdl_import.transformed_normals(record['normals'],matrix)
 result['import']=rdl_import.apply(data)
 for name,values in normals.items():
  item=next(i for i in modo.Scene().items('mesh') if i.name==name)
  geo=item.geometry;maps=geo.vmaps['RDL Normals'];assert len(maps)==1;nmap=maps[0]
  uvmap=geo.vmaps['RDL UV'][0]
  for f,face in enumerate(geo.polygons):
   indices=[v.index for v in face.vertices]
   assert indices==(list(reversed(faces[f])) if name.endswith('mirrored') else faces[f]),(name,indices)
   for c,v in enumerate(face.vertices):
    actual=nmap.getNormal(v) if name.startswith('point') else nmap.getNormal(v,face)
    source_corner=faces[f].index(v.index)
    expected=values[v.index] if name.startswith('point') else values[f*3+source_corner]
    uv=face.getUV(v,uvmap)
    expected_uv=data['meshes'][0]['uv'][f*3+source_corner]
    assert all(abs(a-b)<1e-6 for a,b in zip(uv,expected_uv)),(name,'UV',str(uv),expected_uv)
    assert all(abs(a-b)<1e-6 for a,b in zip(actual,expected)),(name,f,c,str(actual),expected)
 result['ok']=True
except Exception:result['error']=traceback.format_exc()
finally:
 (out/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
 QtCore.QTimer.singleShot(100,lambda:lx.eval('!app.quit'))
