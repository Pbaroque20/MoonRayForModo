"""VDB volume test scenes: make_vdb_scenes.py <folder> <vdb folder>. VdbGeometry with VdbVolume over a floor under a
rect light and the environment: a fog sphere (linear interpolation), a lumpy box (nearest and quadratic), a thin
shell (small voxels), the sphere emitting by its temperature grid (lighting the floor), a moved and turned sphere,
and the sphere against the sky alone (its alpha)."""
import math
import sys
from pathlib import Path

folder = Path(sys.argv[1]).resolve()
vdb = Path(sys.argv[2]).resolve()
folder.mkdir(parents=True, exist_ok=True)


def mat(m):
    return 'Mat4(%s)' % ','.join('%.9g' % v for row in m for v in row)


def translate(x, y, z):
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [x, y, z, 1]]


def mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[1, 0, 0, 0], [0, c, s, 0], [0, -s, c, 0], [0, 0, 0, 1]]


def rot_y(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, 0, -s, 0], [0, 1, 0, 0], [s, 0, c, 0], [0, 0, 0, 1]]


CAM = mul(rot_x(-12), translate(0, 1.6, 5.0))


def scene(geometry, shader, floor=True, extra_sv=''):
    lines = [
        'SceneVariables { ["image_width"]=320, ["image_height"]=200, ["pixel_samples"]=16, ["sampling_mode"]=0, ["frame"]=0, ["max_depth"]=4, '
        '["max_diffuse_depth"]=2, ["lights_visible_in_camera"]=false, ["enable_motion_blur"]=false, ["enable_dof"]=false, ["two_stage_output"]=false, '
        '["russian_roulette_threshold"]=0%s }' % extra_sv,
        'PerspectiveCamera("/camera") { ["node_xform"]=%s, ["focal"]=35.0, ["film_width_aperture"]=36.0, ["near"]=0.01, ["far"]=1000.0 }' % mat(CAM),
        'SceneVariables { ["camera"]=PerspectiveCamera("/camera") }',
        'RenderOutput("/beauty") { ["file_name"]="OUTPUT", ["result"]=0, ["channel_format"]=1, ["compression"]=1 }',
        'RenderOutput("/alpha") { ["file_name"]="OUTPUT", ["result"]=1, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="A" }',
        'RenderOutput("/depth") { ["file_name"]="OUTPUT", ["result"]=2, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="Z" }',
        geometry, shader,
        'RdlMeshGeometry("/floor") { ["vertex_list_0"]={Vec3(-6,0,6),Vec3(6,0,6),Vec3(6,0,-6),Vec3(-6,0,-6)}, ["face_vertex_count"]={4}, ["vertices_by_index"]={0,1,2,3}, ["is_subd"]=false, ["smooth_normal"]=false }',
        'UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }',
        'EnvLight("/fill") { ["intensity"]=0.3 }',
        'RectLight("/key") { ["node_xform"]=%s, ["width"]=3, ["height"]=2, ["intensity"]=5 }' % mat([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [1.5, 4, 2, 1]]),
        'LightSet("/lights") { RectLight("/key"), EnvLight("/fill") }',
    ]
    geoms = ['VdbGeometry("/vdb")'] + (['RdlMeshGeometry("/floor")'] if floor else [])
    lines.append('GeometrySet("/geometry") { %s }' % ', '.join(geoms))
    entries = ['{ VdbGeometry("/vdb"), "", LightSet("/lights"), VdbVolume("/vol") }']
    if floor:
        entries.append('{ RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") }')
    lines += ['Layer("/layer") { %s }' % ', '.join(entries), 'SceneVariables { ["layer"]=Layer("/layer") }', '']
    return '\n'.join(lines)


def geometry(name, interpolation=1, xform=None, emission=''):
    attrs = ['["model"]="%s"' % (vdb / name).as_posix(), '["interpolation"]=%d' % interpolation]
    if emission:
        attrs.append('["emission_grid"]="%s"' % emission)
    attrs.append('["node_xform"]=%s' % mat(xform or translate(0, 1.1, 0)))
    return 'VdbGeometry("/vdb") { %s }' % ', '.join(attrs)


FOG = 'VdbVolume("/vol") { ["opacity_gain_mult"]=Rgb(3,3,3), ["color_mult"]=Rgb(0.85,0.8,0.75), ["incandescence_gain_mult"]=Rgb(0,0,0), ["anisotropy"]=0.3 }'
GLOW = 'VdbVolume("/vol") { ["opacity_gain_mult"]=Rgb(2,2,2), ["color_mult"]=Rgb(0.6,0.6,0.6), ["incandescence_gain_mult"]=Rgb(6,2.5,0.8), ["anisotropy"]=0.0 }'
cases = {
    'vdb-sphere': scene(geometry('sphere.vdb'), FOG),
    'vdb-noise-nearest': scene(geometry('noise.vdb', 0), FOG),
    'vdb-noise-quadratic': scene(geometry('noise.vdb', 2), FOG),
    'vdb-shell': scene(geometry('shell.vdb'), FOG),
    'vdb-emission': scene(geometry('sphere.vdb', emission='Cd'), GLOW),
    'vdb-xform': scene(geometry('sphere.vdb', xform=mul(mul([[1.3, 0, 0, 0], [0, 0.8, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]], rot_y(30)), translate(0.3, 1.0, -0.2))), FOG),
    'vdb-alpha': scene(geometry('sphere.vdb'), FOG, floor=False),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
