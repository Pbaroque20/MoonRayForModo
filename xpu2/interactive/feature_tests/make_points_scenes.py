"""Point test scenes: make_points_scenes.py <folder>. RdlPointGeometry spheres on a floor: radii one a point, one for
all and none, colours and texture coordinates as primitive attributes, a moved node transform, and under motion blur
velocities, accelerations, a second vertex list (with the static case's first list kept) and a moving transform."""
import math
import random
import sys
from pathlib import Path

folder = Path(sys.argv[1]).resolve()
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


CAM = mul(rot_x(-14), translate(0, 2.2, 6.0))
rng = random.Random(7)
N = 60
P = [(rng.uniform(-2.2, 2.2), rng.uniform(0.15, 1.6), rng.uniform(-1.5, 1.2)) for _ in range(N)]
R = [rng.uniform(0.06, 0.28) for _ in range(N)]
C = [(rng.random(), rng.random(), rng.random()) for _ in range(N)]
UV = [(rng.random(), rng.random()) for _ in range(N)]
V = [(rng.uniform(-3, 3), rng.uniform(-1, 1), rng.uniform(-3, 3)) for _ in range(N)]
A = [(rng.uniform(-20, 20), rng.uniform(-20, 20), 0) for _ in range(N)]
P1 = [(x + 0.3, y + 0.1, z - 0.2) for x, y, z in P]


def vec3s(v):
    return '{' + ','.join('Vec3(%.6g,%.6g,%.6g)' % p for p in v) + '}'


def scene(points, extra='', material='DwaBaseMaterial("/m")', motion=False):
    return '\n'.join([
        'SceneVariables { ["image_width"]=320, ["image_height"]=200, ["pixel_samples"]=16, ["sampling_mode"]=0, ["frame"]=0, ["max_depth"]=4, '
        '["max_diffuse_depth"]=2, ["lights_visible_in_camera"]=false, ["enable_motion_blur"]=%s, ["enable_dof"]=false, ["two_stage_output"]=false, '
        '["russian_roulette_threshold"]=0, ["motion_steps"]={-0.25, 0.25} }' % ('true' if motion else 'false'),
        'PerspectiveCamera("/camera") { ["node_xform"]=%s, ["focal"]=35.0, ["film_width_aperture"]=36.0, ["near"]=0.01, ["far"]=1000.0 }' % mat(CAM),
        'SceneVariables { ["camera"]=PerspectiveCamera("/camera") }',
        'RenderOutput("/beauty") { ["file_name"]="OUTPUT", ["result"]=0, ["channel_format"]=1, ["compression"]=1 }',
        'RenderOutput("/alpha") { ["file_name"]="OUTPUT", ["result"]=1, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="A" }',
        'RenderOutput("/n") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=2, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="N" }',
        'RenderOutput("/st") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=3, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="St" }',
        'RenderOutput("/motion") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=12, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="motion" }',
        'RdlMeshGeometry("/floor") { ["vertex_list_0"]={Vec3(-6,0,6),Vec3(6,0,6),Vec3(6,0,-6),Vec3(-6,0,-6)}, ["face_vertex_count"]={4}, ["vertices_by_index"]={0,1,2,3}, ["is_subd"]=false, ["smooth_normal"]=false }',
        'CheckerboardMap("/checker") { ["num_u_tiles"]=4, ["num_v_tiles"]=4, ["color_A"]=Rgb(0.9,0.85,0.8), ["color_B"]=Rgb(0.15,0.2,0.5) }',
        'DwaBaseMaterial("/m") { ["albedo"]=Rgb(0.7,0.5,0.3), ["roughness"]=0.3, ["specular"]=1.0 }',
        'AttributeMap("/am") { ["map_type"]=0, ["primitive_attribute_name"]="pt_color", ["primitive_attribute_type"]=3, ["default_value"]=Rgb(1,0,1) }',
        'DwaBaseMaterial("/ma") { ["albedo"]=bind(AttributeMap("/am"), Rgb(1,1,1)), ["roughness"]=0.4, ["specular"]=1.0 }',
        'DwaBaseMaterial("/mt") { ["albedo"]=bind(CheckerboardMap("/checker"), Rgb(1,1,1)), ["roughness"]=0.4, ["specular"]=1.0 }',
        'UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }',
        extra,
        points,
        'EnvLight("/fill") { ["intensity"]=0.3 }',
        'RectLight("/key") { ["node_xform"]=%s, ["width"]=3, ["height"]=2, ["intensity"]=4 }' % mat([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [1.5, 4, 2, 1]]),
        'LightSet("/lights") { RectLight("/key"), EnvLight("/fill") }',
        'GeometrySet("/geometry") { RdlPointGeometry("/pts"), RdlMeshGeometry("/floor") }',
        'Layer("/layer") { { RdlPointGeometry("/pts"), "", %s, LightSet("/lights") }, '
        '{ RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") } }' % material,
        'SceneVariables { ["layer"]=Layer("/layer") }', ''])


RADII = '{' + ','.join('%.6g' % r for r in R) + '}'
BASE = '["vertex_list_0"]=%s' % vec3s(P)
cases = {
    'pt-static': scene('RdlPointGeometry("/pts") { %s, ["radius_list"]=%s }' % (BASE, RADII)),
    'pt-radius-one': scene('RdlPointGeometry("/pts") { %s, ["radius_list"]={0.12} }' % BASE),
    'pt-radius-none': scene('RdlPointGeometry("/pts") { ["vertex_list_0"]=%s }' % vec3s([(x * 1.4, 0.5, z * 1.4) for x, _, z in P[:12]])),
    'pt-attrs': scene('RdlPointGeometry("/pts") { %s, ["radius_list"]=%s, ["primitive_attributes"]={UserData("/ud")} }' % (BASE, RADII),
                      'UserData("/ud") { ["color_key"]="pt_color", ["color_values_0"]={%s} }' % ','.join('Rgb(%.4g,%.4g,%.4g)' % c for c in C),
                      material='DwaBaseMaterial("/ma")'),
    'pt-uv': scene('RdlPointGeometry("/pts") { %s, ["radius_list"]=%s, ["primitive_attributes"]={UserData("/uv")} }' % (BASE, RADII),
                   'UserData("/uv") { ["vec2f_key"]="uv", ["vec2f_values_0"]={%s} }' % ','.join('Vec2(%.4g,%.4g)' % c for c in UV),
                   material='DwaBaseMaterial("/mt")'),
    'pt-xform': scene('RdlPointGeometry("/pts") { ["node_xform"]=%s, %s, ["radius_list"]=%s }'
                      % (mat(mul(rot_y(30), translate(0.3, 0.1, -0.2))), BASE, RADII)),
    'pt-mb-velocity': scene('RdlPointGeometry("/pts") { %s, ["radius_list"]=%s, ["velocity_list_0"]=%s, ["motion_blur_type"]=1 }'
                            % (BASE, RADII, vec3s(V)), motion=True),
    'pt-mb-accel': scene('RdlPointGeometry("/pts") { %s, ["radius_list"]=%s, ["velocity_list_0"]=%s, ["accleration_list"]=%s, ["motion_blur_type"]=3 }'
                         % (BASE, RADII, vec3s(V), vec3s(A)), motion=True),
    'pt-mb-delta': scene('RdlPointGeometry("/pts") { %s, ["vertex_list_1"]=%s, ["radius_list"]=%s }' % (BASE, vec3s(P1), RADII), motion=True),
    'pt-static-second': scene('RdlPointGeometry("/pts") { %s, ["vertex_list_1"]=%s, ["radius_list"]=%s }' % (BASE, vec3s(P1), RADII)),
    'pt-mb-xform': scene('RdlPointGeometry("/pts") { ["node_xform"]=blur(%s, %s), %s, ["radius_list"]=%s }'
                         % (mat(translate(0, 0, 0)), mat(mul(rot_y(15), translate(0.4, 0, 0))), BASE, RADII), motion=True),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
