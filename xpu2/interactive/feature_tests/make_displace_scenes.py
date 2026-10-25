"""Displaced subdivision surfaces and moving displaced meshes: make_displace_scenes.py <folder> <gray.tx>. The subd cube
of make_subd_scenes.py displaced by a noise and by a grey image, uniformly and camera-adaptively, in motion, and with
enable_displacement off; a polygon grid displaced in motion."""
import math
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
source = (here / 'make_subd_scenes.py').read_text(encoding='utf-8')
defs = source[:source.index('cases = {}')]
namespace = {'__file__': str(here / 'make_subd_scenes.py')}
argv = sys.argv
sys.argv = [argv[0], str(here / '_displace_tmp')]
exec(compile(defs, 'make_subd_scenes.py', 'exec'), namespace)
sys.argv = argv
folder = Path(sys.argv[1]).resolve()
gray = Path(sys.argv[2]).resolve().as_posix()
folder.mkdir(parents=True, exist_ok=True)
scene, mesh, cube, grid = namespace['scene'], namespace['mesh'], namespace['cube'], namespace['grid']

MATS = '\n'.join([
    'NoiseMap_v2("/bumps") { ["space"]=2, ["frequency_multiplier"]=3.0, ["max_level"]=4.5, ["color_A"]=Rgb(0,0,0), ["color_B"]=Rgb(1,1,1) }',
    'ImageMap("/img") { ["texture"]="%s" }' % gray,
    'NormalDisplacement("/dn") { ["height"]=bind(NoiseMap_v2("/bumps"),1.0), ["zero_value"]=0.5, ["height_multiplier"]=0.15 }',
    'NormalDisplacement("/di") { ["height"]=bind(ImageMap("/img"),1.0), ["height_multiplier"]=0.08 }',
    'DwaBaseMaterial("/subd_m") { ["albedo"]=Rgb(0.8,0.45,0.25), ["roughness"]=0.35, ["specular"]=1.0 }',
])


def layer(displacement):
    return ('Layer("/layer") { { RdlMeshGeometry("/s"), "", DwaBaseMaterial("/subd_m"), LightSet("/lights"), NormalDisplacement("%s") },'
            '{ RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") } }' % displacement)


def motion(text):
    text = text.replace('["enable_motion_blur"]=false', '["enable_motion_blur"]=true, ["motion_steps"]={-0.25, 0.25}')
    return text.replace('RenderOutput("/dsdx")', 'RenderOutput("/motion") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=12, ["channel_format"]=1, '
                        '["compression"]=1, ["channel_name"]="motion" }\nRenderOutput("/dsdx")')


def v3(vs):
    return '{' + ','.join('Vec3(%g,%g,%g)' % p for p in vs) + '}'


v, f, uv = cube(1.4, (0, 1.0, 0))
second = [(x + 0.3, y + 0.05, z - 0.15) for x, y, z in v]
gv, gf, guv = grid(8, 3.0, (0, 0.4, 0))
poly = ('RdlMeshGeometry("/s") { ["vertex_list"]=%s, ["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}, ["uv_list"]=%s, ["is_subd"]=false, '
        '["smooth_normal"]=true, ["mesh_resolution"]=4, ["vertex_list_1"]=%s }'
        % (v3(gv), ','.join('4' for _ in gf), ','.join(str(i) for q in gf for i in q), '{' + ','.join('Vec2(%g,%g)' % p for p in guv) + '}',
           v3([(x + 0.25, y + 0.1, z) for x, y, z in gv])))
cases = {
    'dsp-subd-noise': scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=12'), MATS, layer('/dn')),
    'dsp-subd-image': scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=12'), MATS, layer('/di')),
    'dsp-subd-adaptive': scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=24, ["adaptive_error"]=2.0'), MATS, layer('/dn')),
    'dsp-subd-mb': motion(scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=12, ["vertex_list_1"]=%s' % v3(second)), MATS, layer('/dn'))),
    'dsp-poly-mb': motion(scene(poly, MATS, layer('/dn'))),
    'dsp-subd-off': scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=12'), MATS, layer('/dn')).replace(
        'SceneVariables { ["image_width"]', 'SceneVariables { ["enable_displacement"]=false, ["image_width"]'),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
