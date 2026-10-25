"""VDB light filters and mesh lights on subdivision surfaces: make_light_more_scenes.py <folder> <sphere.vdb>.
The light filter scenes' spot through a VdbLightFilter over the fog sphere's grid (tinted; inverted and remapped;
gaussian and spherical blur; quadratic interpolation; a missing file, density 1); the light scenes' mesh light on a
subdivided cube, whole and one part of it."""
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
folder = Path(sys.argv[1]).resolve()
vdb = Path(sys.argv[2]).resolve().as_posix()
folder.mkdir(parents=True, exist_ok=True)

source = (here / 'make_filter_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('cases = {')]
ns = {'__file__': str(here / 'make_filter_scenes.py')}
argv = sys.argv
sys.argv = [argv[0], str(folder)]
exec(compile(defs, 'make_filter_scenes.py', 'exec'), ns)
sys.argv = argv
scene, mat, translate = ns['scene'], ns['mat'], ns['translate']


def scaled(s, x, y, z):
    return [[s, 0, 0, 0], [0, s, 0, 0], [0, 0, s, 0], [x, y, z, 1]]


def vdb_filter(extra=''):
    return scene('VdbLightFilter("/f") { ["node_xform"]=%s, ["vdb_map"]="%s", ["color_tint"]=Rgb(0.15,0.35,1.0)%s }'
                 % (mat(scaled(2.2, 0.2, 0.0, 0.6)), vdb, extra), 'VdbLightFilter("/f")')


cases = {
    'lfv-basic': vdb_filter(),
    'lfv-remap': vdb_filter(', ["invert_density"]=true, ["density_rescale_enable"]=true, ["density_remap_input_min"]=0.1, ["density_remap_input_max"]=0.9, '
                            '["density_remap_inputs"]={0,0.5,1}, ["density_remap_outputs"]={0,1,0.3}, ["density_remap_interpolation_types"]={1,1,1}'),
    'lfv-blur': vdb_filter(', ["blur_value"]=0.4, ["blur_type"]=0'),
    'lfv-sphere-blur': vdb_filter(', ["blur_value"]=0.4, ["blur_type"]=1'),
    'lfv-quadratic': vdb_filter(', ["vdb_interpolation_type"]=2'),
    'lfv-missing': scene('VdbLightFilter("/f") { ["vdb_map"]="%s/none.vdb", ["color_tint"]=Rgb(0.15,0.35,1.0) }' % folder.as_posix(), 'VdbLightFilter("/f")'),
}

src = (here / 'make_light_scenes2.py').read_text(encoding='utf-8')
lns = {'__file__': str(here / 'make_light_scenes2.py')}
sys.argv = [argv[0], str(folder), ns['TEX'], '16']
exec(compile(src[:src.index('CASES = {')], 'make_light_scenes2.py', 'exec'), lns)
sys.argv = argv
BASE, GEOM, LAYER, FILL, mesh = lns['BASE'], lns['GEOM'], lns['LAYER'], lns['FILL'], lns['mesh']
# A cube over the balls (its faces facing out), subdivided; parts: its bottom face alone.
cv = [(-0.9, 3.0, -0.9), (0.9, 3.0, -0.9), (0.9, 3.0, 0.9), (-0.9, 3.0, 0.9), (-0.9, 4.2, -0.9), (0.9, 4.2, -0.9), (0.9, 4.2, 0.9), (-0.9, 4.2, 0.9)]
cf = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)]
SUBD = ', ["mesh_resolution"]=6, ["part_list"]={"bottom","rest"}, ["part_face_count_list"]={1,5}, ["part_face_indices"]={0,1,2,3,4,5}'
emitter = mesh('/emitter', cv, cf, SUBD).replace('["is_subd"]=false', '["is_subd"]=true')
for name, parts in (('ml-subd', ''), ('ml-subd-part', ', ["parts"]={"bottom"}')):
    light = FILL + 'MeshLight("/key") { ["geometry"]=RdlMeshGeometry("/emitter"), ["intensity"]=3, ["visible_in_camera"]=1%s }\n' % parts
    cases[name] = BASE + light + 'LightSet("/lights") { EnvLight("/fill"), MeshLight("/key") }\n' + GEOM + emitter + LAYER
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
