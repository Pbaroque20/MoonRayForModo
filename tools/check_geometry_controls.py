"""Deferred pure-data geometry checks; does not start Modo or render."""
import copy,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import geometry,options
mesh={'vertices':[[0,0,0],[1,0,0],[0,1,0],[0,0,1]],'faces':[[0,1,2],[1,0,3]],'normals':[[0,0,1]]*6,
 'geometry_settings':{'override':True,'normal_override':True,'smoothing_angle':30.}}
original=copy.deepcopy(mesh)
sharp=geometry.prepare(mesh);assert sharp['normals'][0]==[0.,0.,1.]
assert mesh==original
mesh['geometry_settings']['smoothing_angle']=100.
soft=geometry.prepare(mesh);assert soft['normals'][0][1]>0 and soft['normals'][0][2]>0
mesh['geometry_settings']['normal_override']=False
assert geometry.prepare(mesh)['normals']==mesh['normals']
mesh.update(subdivision=True,subdivision_level=3)
mesh['geometry_settings'].update(angular_tessellation=True,tessellation_angle=10.,level=3)
assert geometry.prepare(mesh)['mesh_resolution']==8
mesh['geometry_settings']['tessellation_angle']=45.
assert geometry.prepare(mesh)['mesh_resolution']==2
mesh.update(evaluated_geometry=True,subdivision=False)
assert 'mesh_resolution' not in geometry.prepare(mesh)
for invalid in (float('nan'),-1,181):
 try: options.object_values({'smoothing_angle':invalid})
 except ValueError: pass
 else: raise AssertionError('invalid angle accepted')
print('Geometry controls passed')
