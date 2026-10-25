"""Motion blur test scenes: make_motion_scenes.py <folder>. A textured cube on a floor under a rect light: the camera
moving (translation, rotation, zoom; perspective, orthographic, fisheye), the cube moving (its transform, a second
vertex list, velocities, accelerations, Hermite), the shutter apart from the motion steps and biased, motion blur off
with animated data, and a light with a blurred transform but no mb switch. Beauty, alpha, depth, motion vectors, P, N,
St and dPds."""
import math
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


def blur(a, b):
    return 'blur(%s, %s)' % (mat(a), mat(b))


def cube(size=1.0):
    s = size / 2
    v = [(x * s, y * s, z * s) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    uv = []
    for fi, f in enumerate(faces):
        u0, v0 = (fi % 3) / 3.0, (fi // 3) / 2.0
        uv += [(u0 + 0.02, v0 + 0.02), (u0 + 0.31, v0 + 0.02), (u0 + 0.31, v0 + 0.48), (u0 + 0.02, v0 + 0.48)]
    return v, faces, uv


def vec3s(pts):
    return '{' + ','.join('Vec3(%.9g,%.9g,%.9g)' % p for p in pts) + '}'


def mesh(xform, extra='', smooth=False):
    v, faces, uv = cube()
    counts = ','.join(str(len(f)) for f in faces)
    idx = ','.join(str(i) for f in faces for i in f)
    ul = '{' + ','.join('Vec2(%g,%g)' % p for p in uv) + '}'
    return ('RdlMeshGeometry("/s") { ["node_xform"]=%s, ["vertex_list_0"]=%s, ["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}, '
            '["uv_list"]=%s, ["is_subd"]=false, ["smooth_normal"]=%s%s }' % (xform, vec3s(v), counts, idx, ul, 'true' if smooth else 'false', extra))


def scene(camera_xform, geometry, camera_class='PerspectiveCamera', camera_extra='', sv_extra='', light_xform=None, motion=True, lights=None):
    light = light_xform or mat([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [1.5, 4, 2, 1]])
    key = ['RectLight("/key") { ["node_xform"]=%s, ["width"]=3, ["height"]=2, ["intensity"]=4 }' % light,
           'LightSet("/lights") { RectLight("/key"), EnvLight("/fill") }']
    if lights:
        key = [lights[0], 'LightSet("/lights") { %s, EnvLight("/fill") }' % lights[1]]
    return '\n'.join([
        'SceneVariables { ["image_width"]=320, ["image_height"]=200, ["pixel_samples"]=16, ["sampling_mode"]=0, ["frame"]=0, ["max_depth"]=4, '
        '["max_diffuse_depth"]=2, ["lights_visible_in_camera"]=false, ["enable_motion_blur"]=%s, ["enable_dof"]=false, ["two_stage_output"]=false, '
        '["russian_roulette_threshold"]=0, ["motion_steps"]={-0.25, 0.25}%s }' % ('true' if motion else 'false', sv_extra),
        '%s("/camera") { ["node_xform"]=%s, ["near"]=0.01, ["far"]=1000.0%s }' % (camera_class, camera_xform, camera_extra),
        'SceneVariables { ["camera"]=%s("/camera") }' % camera_class,
        'RenderOutput("/beauty") { ["file_name"]="OUTPUT", ["result"]=0, ["channel_format"]=1, ["compression"]=1 }',
        'RenderOutput("/alpha") { ["file_name"]="OUTPUT", ["result"]=1, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="A" }',
        'RenderOutput("/depth") { ["file_name"]="OUTPUT", ["result"]=2, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="Z" }',
        'RenderOutput("/motion") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=12, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="motion" }',
        'RenderOutput("/p") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=0, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="P" }',
        'RenderOutput("/n") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=2, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="N" }',
        'RenderOutput("/st") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=3, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="St" }',
        'RenderOutput("/dpds") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=4, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="dPds" }',
        geometry,
        'RdlMeshGeometry("/floor") { ["vertex_list_0"]={Vec3(-6,0,6),Vec3(6,0,6),Vec3(6,0,-6),Vec3(-6,0,-6)}, ["face_vertex_count"]={4}, ["vertices_by_index"]={0,1,2,3}, ["is_subd"]=false, ["smooth_normal"]=false }',
        'CheckerboardMap("/checker") { ["num_u_tiles"]=12, ["num_v_tiles"]=12, ["color_A"]=Rgb(0.9,0.85,0.8), ["color_B"]=Rgb(0.15,0.2,0.5) }',
        'DwaBaseMaterial("/m") { ["albedo"]=bind(CheckerboardMap("/checker"), Rgb(1,1,1)), ["roughness"]=0.3, ["specular"]=1.0 }',
        'UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }',
        'EnvLight("/fill") { ["intensity"]=0.3 }',
        *key,
        'GeometrySet("/geometry") { RdlMeshGeometry("/s"), RdlMeshGeometry("/floor") }',
        'Layer("/layer") { { RdlMeshGeometry("/s"), "", DwaBaseMaterial("/m"), LightSet("/lights") }, '
        '{ RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") } }',
        'SceneVariables { ["layer"]=Layer("/layer") }', ''])


PERSP = ', ["focal"]=35.0, ["film_width_aperture"]=36.0'
STILL = mat(CAM)
HERE = translate(0, 1, 0)
TURN = mul(mul(rot_y(25), rot_x(10)), translate(0.45, 1.15, 0))
v0, _, _ = cube()
v1 = [(x + 0.5, y + 0.15 * (1 if x > 0 else -1), z - 0.2) for x, y, z in v0]
vel = [(2.4 + 0.6 * y, 0.4, -0.8 * x) for x, y, z in v0]
acc = [(0.0, -9.0, 4.0 * z) for x, y, z in v0]
vel1 = [(-1.2, 1.6, 0.8 * x) for x, y, z in v0]

cases = {
    # The camera's motion.
    'mb-cam-move': scene(blur(CAM, mul(CAM, translate(0.5, 0.1, 0))), mesh(mat(HERE)), camera_extra=PERSP),
    'mb-cam-turn': scene(blur(CAM, mul(rot_y(9), CAM)), mesh(mat(HERE)), camera_extra=PERSP),
    'mb-cam-zoom': scene(STILL, mesh(mat(HERE)), camera_extra=', ["focal"]=blur(30.0, 50.0), ["film_width_aperture"]=36.0'),
    'mb-cam-ortho': scene(blur(CAM, mul(rot_y(6), mul(CAM, translate(0.4, 0, 0)))), mesh(mat(HERE)), 'OrthographicCamera',
                          ', ["film_width_aperture"]=6.0'),
    'mb-cam-fisheye': scene(blur(CAM, mul(rot_y(10), CAM)), mesh(mat(HERE)), 'FisheyeCamera', ', ["fov"]=150.0'),
    # The cube's motion.
    'mb-mesh-xform': scene(STILL, mesh(blur(HERE, TURN)), camera_extra=PERSP),
    'mb-mesh-delta': scene(STILL, mesh(mat(HERE), ', ["vertex_list_1"]=%s' % vec3s(v1), smooth=True), camera_extra=PERSP),
    'mb-mesh-velocity': scene(STILL, mesh(mat(HERE), ', ["velocity_list_0"]=%s, ["velocity_scale"]=1.5' % vec3s(vel)), camera_extra=PERSP),
    'mb-mesh-accel': scene(STILL, mesh(mat(HERE), ', ["velocity_list_0"]=%s, ["accleration_list"]=%s, ["curved_motion_blur_sample_count"]=6'
                                       % (vec3s(vel), vec3s(acc))), camera_extra=PERSP),
    'mb-mesh-hermite': scene(STILL, mesh(mat(HERE), ', ["vertex_list_1"]=%s, ["velocity_list_0"]=%s, ["velocity_list_1"]=%s'
                                         % (vec3s(v1), vec3s(vel), vec3s(vel1)), smooth=True), camera_extra=PERSP),
    # Both, a shutter apart from the motion steps, and a bias.
    'mb-both-shutter': scene(blur(CAM, mul(CAM, translate(-0.3, 0, 0.4))), mesh(blur(HERE, TURN), ', ["vertex_list_1"]=%s' % vec3s(v1)),
                             camera_extra=PERSP + ', ["mb_shutter_open"]=-0.1, ["mb_shutter_close"]=0.4, ["mb_shutter_bias"]=0.6',
                             sv_extra=', ["motion_steps"]={-0.5, 0.5}'),
    # Motion blur off: the frame's time (the cube's transform lerped there, vertex_list_1 in place of the first list).
    'mb-off': scene(blur(CAM, mul(CAM, translate(0.5, 0, 0))), mesh(blur(HERE, TURN), ', ["vertex_list_1"]=%s' % vec3s(v1)),
                    camera_extra=PERSP, motion=False),
    # A light moving without its mb switch: still, at the first time step.
    'mb-light-still': scene(STILL, mesh(mat(HERE)), camera_extra=PERSP,
                            light_xform=blur([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [1.5, 4, 2, 1]], [[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [-2.5, 4, 2, 1]])),
}
# Lights in motion (their mb switch): a textured rect moving and turning, a sphere moving and growing, a spot turning,
# a distant light turning, a disk and a cylinder moving.
TEX = (folder.parent / 'lt' / 'tex.tx').as_posix()
DOWN = [[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [1.5, 4, 2, 1]]
cases['mb-light-rect'] = scene(STILL, mesh(mat(HERE)), camera_extra=PERSP, lights=(
    'RectLight("/k") { ["node_xform"]=%s, ["width"]=3, ["height"]=2, ["intensity"]=4, ["mb"]=true, ["texture"]="%s" }'
    % (blur(DOWN, mul(rot_y(35), mul(DOWN, translate(-2.5, 0, 0)))), TEX), 'RectLight("/k")'))
cases['mb-light-sphere'] = scene(STILL, mesh(mat(HERE)), camera_extra=PERSP, lights=(
    'SphereLight("/k") { ["node_xform"]=%s, ["radius"]=0.3, ["intensity"]=8, ["mb"]=true }'
    % blur(translate(1.6, 2.4, 1.0), [[2, 0, 0, 0], [0, 2, 0, 0], [0, 0, 2, 0], [-1.4, 2.0, 1.5, 1]]), 'SphereLight("/k")'))
cases['mb-light-spot'] = scene(STILL, mesh(mat(HERE)), camera_extra=PERSP, lights=(
    'SpotLight("/k") { ["node_xform"]=%s, ["intensity"]=40, ["outer_cone_angle"]=40, ["inner_cone_angle"]=20, ["mb"]=true }'
    % blur(mul(rot_x(-70), translate(0, 4, 2)), mul(mul(rot_x(-70), rot_y(30)), translate(0.5, 4, 2))), 'SpotLight("/k")'))
cases['mb-light-distant'] = scene(STILL, mesh(mat(HERE)), camera_extra=PERSP, lights=(
    'DistantLight("/k") { ["node_xform"]=%s, ["intensity"]=3, ["angular_extent"]=3, ["mb"]=true }'
    % blur(rot_x(-60), mul(rot_x(-60), rot_y(40))), 'DistantLight("/k")'))
cases['mb-light-disk-cyl'] = scene(STILL, mesh(mat(HERE)), camera_extra=PERSP, lights=(
    'DiskLight("/k") { ["node_xform"]=%s, ["radius"]=0.8, ["intensity"]=6, ["mb"]=true }\n'
    'CylinderLight("/c") { ["node_xform"]=%s, ["radius"]=0.15, ["height"]=1.5, ["intensity"]=5, ["mb"]=true }'
    % (blur(DOWN, mul(DOWN, translate(-2, 0, 0.5))), blur(translate(-1.5, 1.0, 1.0), mul(rot_x(50), translate(1.8, 1.2, 1.2)))),
    'DiskLight("/k"), CylinderLight("/c")'))
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
