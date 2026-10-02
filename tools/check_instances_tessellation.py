"""Deferred export regressions: no Modo launch, GPU or scene modification."""
import copy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import geometry,evaluated,rdla
identity=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
shift=identity[:];shift[12]=3
mesh={'name':'prototype','identity':'prototype','vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]],
 'subdivision':True,'subdivision_level':3,'instances':[identity,shift],'instance_ids':['a','b'],
 'geometry_settings':{'override':True,'dynamic_tessellation':True}}
original=copy.deepcopy(mesh)
meshes=list(geometry.render_meshes([mesh]))
assert len(meshes)==2 and all('instances' not in m and m['adaptive_error']==2 for m in meshes)
assert meshes[1]['matrix']==shift and mesh==original
mesh['geometry_settings']['dynamic_tessellation']=False
assert len(list(geometry.render_meshes([mesh])))==1
segment={'vertices':mesh['vertices'],'faces':mesh['faces'],'uv_sets':[],'normals':[]}
surface={'source_id':1,'source_item':'replicator','material':'','visibility':[True]*6,'layers':[],
 'matrix':identity,'instanced':True,'instance_index':0}
data={'prototypes':{'1':{'features':[],'segments':[segment]}},'surfaces':[surface,dict(surface,matrix=shift,instance_index=1)]}
export=evaluated.meshes(data,{'':{}},[])
assert len(export)==1 and len(export[0]['instances'])==2
assert export[0]['instances'][1]==shift
scene={'camera':{'matrix':identity,'focal_mm':50,'film_mm':36},'materials':{'':{}},'lights':[],'meshes':export}
text=rdla.scene_text(scene)
assert text.count('local geometry = RdlMeshGeometry')==1 and 'local instances = RdlInstancerGeometry' in text
# A lone replica remains an instance, preventing structure changes as counts vary.
data['surfaces']=data['surfaces'][:1]
assert len(evaluated.meshes(data,{'':{}},[])[0]['instances'])==1
# Visibility overrides partition prototypes instead of leaking between replicas.
data['surfaces'].append(dict(surface,matrix=shift,instance_index=2,visibility=[False,True,True,True,True,True]))
assert len(evaluated.meshes(data,{'':{}},[]))==2
print('Instance and tessellation export checks passed')
