"""Curves under motion blur: make_curve_motion_scenes.py <folder>. A patch of strands (linear, Bezier and B-spline;
flat and round) on a floor, moving by a second vertex list, by velocities, by accelerations (curved, several time
steps) and by a moving, scaling node transform; and a static case with a second vertex list given."""
import math
import sys
from pathlib import Path

folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)


def mat(m):
    return 'Mat4(%s)' % ','.join('%.9g' % v for row in m for v in row)


def translate(x, y, z):
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [x, y, z, 1]]


def scale(s):
    return [[s, 0, 0, 0], [0, s, 0, 0], [0, 0, s, 0], [0, 0, 0, 1]]


def mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[1, 0, 0, 0], [0, c, s, 0], [0, -s, c, 0], [0, 0, 0, 1]]


def rot_y(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, 0, -s, 0], [0, 1, 0, 0], [s, 0, c, 0], [0, 0, 0, 1]]


CAM = mul(rot_x(-14), translate(0, 1.2, 4.0))


def strands(kind, count=160, seed=7):
    points_per = {0: 6, 1: 7, 2: 6}[kind]
    state = seed

    def rnd():
        nonlocal state
        state = (state * 1103515245 + 12345) & 0x7fffffff
        return state / 0x7fffffff
    verts, radii, counts, vel, acc = [], [], [], [], []
    for i in range(count):
        x, z = -1.8 + 3.6 * rnd(), -0.6 + 1.2 * rnd()
        height, lean, turn = 0.5 + 0.6 * rnd(), 0.15 + 0.35 * rnd(), 2 * math.pi * rnd()
        vx, vz = 4 * (rnd() - 0.5), 4 * (rnd() - 0.5)
        for k in range(points_per):
            t = k / (points_per - 1)
            bend = lean * t * t
            verts.append((x + bend * math.cos(turn), height * t, z + bend * math.sin(turn)))
            radii.append(0.02 * (1 - t) + 0.006 * t)
            vel.append((vx * t, 0.5 * t, vz * t))
            acc.append((-30 * vz * t, 0, 30 * vx * t))
        counts.append(points_per)
    return verts, radii, counts, vel, acc


def v3(vs):
    return '{' + ','.join('Vec3(%.6g,%.6g,%.6g)' % v for v in vs) + '}'


def curves(kind, subtype, extra='', xform=None, second=None, velocity=False, acceleration=False, mb_type=None, samples=None):
    verts, radii, counts, vel, acc = strands(kind)
    attrs = ['["vertex_list_0"]=%s' % v3(verts), '["radius_list"]={%s}' % ','.join('%.6g' % r for r in radii),
             '["curves_vertex_count"]={%s}' % ','.join(map(str, counts)), '["curve_type"]=%d' % kind,
             '["curves_subtype"]=%d' % subtype, '["tessellation_rate"]=4']
    if second:
        attrs.append('["vertex_list_1"]=%s' % v3([(x + second[0] * y, y + second[1], z + second[2] * y) for x, y, z in verts]))
    if velocity:
        attrs.append('["velocity_list_0"]=%s' % v3(vel))
    if acceleration:
        attrs.append('["accleration_list"]=%s' % v3(acc))
    if mb_type is not None:
        attrs.append('["motion_blur_type"]=%d' % mb_type)
    if samples:
        attrs.append('["curved_motion_blur_sample_count"]=%d' % samples)
    if xform:
        attrs.append('["node_xform"]=%s' % xform)
    return 'RdlCurveGeometry("/hair") { %s }' % ', '.join(attrs)


def scene(geometry, motion=True):
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
        'DwaBaseMaterial("/m") { ["albedo"]=Rgb(0.7,0.5,0.3), ["roughness"]=0.35, ["specular"]=1.0 }',
        'UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }',
        geometry,
        'EnvLight("/fill") { ["intensity"]=0.3 }',
        'RectLight("/key") { ["node_xform"]=%s, ["width"]=3, ["height"]=2, ["intensity"]=4 }' % mat([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [1.5, 4, 2, 1]]),
        'LightSet("/lights") { RectLight("/key"), EnvLight("/fill") }',
        'GeometrySet("/geometry") { RdlCurveGeometry("/hair"), RdlMeshGeometry("/floor") }',
        'Layer("/layer") { { RdlCurveGeometry("/hair"), "", DwaBaseMaterial("/m"), LightSet("/lights") }, '
        '{ RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") } }',
        'SceneVariables { ["layer"]=Layer("/layer") }', ''])


MOVE = 'blur(%s, %s)' % (mat(translate(0, 0, 0)), mat(mul(mul(scale(1.15), rot_y(12)), translate(0.25, 0, 0))))
cases = {
    'cv-delta-linear': scene(curves(0, 0, second=(0.4, 0.05, -0.2))),
    'cv-delta-bezier': scene(curves(1, 0, second=(0.4, 0.05, -0.2))),
    'cv-delta-bspline-round': scene(curves(2, 1, second=(0.4, 0.05, -0.2))),
    'cv-velocity-bspline': scene(curves(2, 0, velocity=True, mb_type=1)),
    'cv-accel-bezier': scene(curves(1, 0, velocity=True, acceleration=True, mb_type=3, samples=4)),
    'cv-xform-linear-round': scene(curves(0, 1, xform=MOVE)),
    'cv-static-second': scene(curves(2, 0, second=(0.4, 0.05, -0.2)), motion=False),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
