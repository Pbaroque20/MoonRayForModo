"""Primitive attributes on subdivision surfaces and the dicing camera: make_subd_primvar_scenes.py <folder>. The subd
cube of make_subd_scenes.py with colours by vertex, by face-vertex and by face read through AttributeMaps, a constant
float scaling roughness, and adaptive tessellation by a dicing camera (the scene's and the geometry's)."""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'make_subd_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('cases = {}')]
namespace = {'__file__': str(here / 'make_subd_scenes.py')}
argv = sys.argv
sys.argv = [argv[0], str(here / '_primvar_tmp')]
exec(compile(defs, 'make_subd_scenes.py', 'exec'), namespace)
sys.argv = argv
folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
scene, mesh, cube, layer = namespace['scene'], namespace['mesh'], namespace['cube'], namespace['layer']

v, f, uv = cube()
nv, nf, nfv = len(v), len(f), sum(len(x) for x in f)
vert_cols = ','.join('Rgb(%g,%g,%g)' % (0.2 + 0.8 * (i & 1), 0.2 + 0.8 * ((i >> 1) & 1), 0.2 + 0.8 * ((i >> 2) & 1)) for i in range(nv))
fv_cols = ','.join('Rgb(%g,%g,%g)' % ((k * 37 % 10) / 10, (k * 53 % 10) / 10, (k * 71 % 10) / 10) for k in range(nfv))
face_vals = ','.join('%g' % (0.2 + 0.13 * i) for i in range(nf))
USER = '\n'.join([
    'UserData("/vc") { ["color_key"]="vcol", ["color_values_0"]={%s}, ["rate"]=4 }' % vert_cols,
    'UserData("/fvc") { ["color_key"]="fvcol", ["color_values_0"]={%s}, ["rate"]=6 }' % fv_cols,
    'UserData("/uf") { ["float_key"]="fval", ["float_values_0"]={%s}, ["rate"]=3 }' % face_vals,
    'UserData("/cf") { ["float_key"]="rough", ["float_values_0"]={0.6}, ["rate"]=1 }',
])
MAT = '\n'.join([
    USER,
    'AttributeMap("/am_v") { ["map_type"]=0, ["primitive_attribute_name"]="vcol", ["primitive_attribute_type"]=3, ["default_value"]=Rgb(1,0,1) }',
    'AttributeMap("/am_fv") { ["map_type"]=0, ["primitive_attribute_name"]="fvcol", ["primitive_attribute_type"]=3, ["default_value"]=Rgb(1,0,1) }',
    'AttributeMap("/am_u") { ["map_type"]=0, ["primitive_attribute_name"]="fval", ["primitive_attribute_type"]=0, ["default_value"]=Rgb(1,0,1) }',
    'AttributeMap("/am_c") { ["map_type"]=0, ["primitive_attribute_name"]="rough", ["primitive_attribute_type"]=0, ["default_value"]=Rgb(1,0,1) }',
])


def dwa(name, albedo_map, rough='0.3'):
    return 'DwaBaseMaterial("/%s") { ["albedo"]=bind(AttributeMap("/%s"), Rgb(1,1,1)), ["roughness"]=%s, ["specular"]=1.0 }' % (name, albedo_map, rough)


attrs = ', ["primitive_attributes"]={UserData("/vc"), UserData("/fvc"), UserData("/uf"), UserData("/cf")}'
cases = {}
for name, amap in (('vertex', 'am_v'), ('facevarying', 'am_fv'), ('uniform', 'am_u'), ('constant', 'am_c')):
    cases['spv-' + name] = scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=8' + attrs),
                                 MAT + '\n' + dwa('subd_m', amap), layer([('/s', '', 'DwaBaseMaterial("/subd_m")')]))
DICER = 'PerspectiveCamera("/dicer") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,1,30,1), ["focal"]=50.0, ["film_width_aperture"]=36.0, ["near"]=0.01, ["far"]=1000.0 }'
base = scene(mesh('/s', v, f, uv, True, ', ["adaptive_error"]=2.0, ["mesh_resolution"]=16'),
             MAT + '\n' + dwa('subd_m', 'am_c'), layer([('/s', '', 'DwaBaseMaterial("/subd_m")')]))
cases['spv-dicing-scene'] = base.replace('SceneVariables { ["camera"]=PerspectiveCamera("/camera") }',
                                         DICER + '\nSceneVariables { ["camera"]=PerspectiveCamera("/camera"), ["dicing_camera"]=PerspectiveCamera("/dicer") }')
cases['spv-dicing-geometry'] = scene(mesh('/s', v, f, uv, True, ', ["adaptive_error"]=2.0, ["mesh_resolution"]=16, ["dicing_camera"]=PerspectiveCamera("/dicer")'),
                                     DICER + '\n' + MAT + '\n' + dwa('subd_m', 'am_c'), layer([('/s', '', 'DwaBaseMaterial("/subd_m")')]))
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
