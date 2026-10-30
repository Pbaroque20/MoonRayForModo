"""Instancer test scenes: make_instance_scenes.py <folder>. A textured cube (the reference, not itself in the geometry
set) instanced by an RdlInstancerGeometry: static transforms (one non-uniformly scaled), per-instance colours through an
AttributeMap, position/orientation/scale attributes, ref indices over two references with disabled indices, and under
motion blur paired close transforms (turning), velocities, and a moving instancer."""
import math
import sys
from pathlib import Path

folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)


def mat(m):
    return 'Mat4(%s)' % ','.join('%.9g' % v for row in m for v in row)


def translate(x, y, z):
    return [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [x, y, z, 1]]


def scale(x, y, z):
    return [[x, 0, 0, 0], [0, y, 0, 0], [0, 0, z, 0], [0, 0, 0, 1]]


def mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(4)) for j in range(4)] for i in range(4)]


def rot_x(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[1, 0, 0, 0], [0, c, s, 0], [0, -s, c, 0], [0, 0, 0, 1]]


def rot_y(deg):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [[c, 0, -s, 0], [0, 1, 0, 0], [s, 0, c, 0], [0, 0, 0, 1]]


CAM = mul(rot_x(-14), translate(0, 2.2, 6.0))


def cube(name, size=0.6):
    s = size / 2
    v = [(x * s, y * s + s, z * s) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    uv = []
    for fi, f in enumerate(faces):
        u0, v0 = (fi % 3) / 3.0, (fi // 3) / 2.0
        uv += [(u0 + 0.02, v0 + 0.02), (u0 + 0.31, v0 + 0.02), (u0 + 0.31, v0 + 0.48), (u0 + 0.02, v0 + 0.48)]
    return ('RdlMeshGeometry("%s") { ["vertex_list_0"]={%s}, ["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}, ["uv_list"]={%s}, '
            '["is_subd"]=false, ["smooth_normal"]=true }' % (name,
                ','.join('Vec3(%g,%g,%g)' % p for p in v), ','.join(str(len(f)) for f in faces),
                ','.join(str(i) for f in faces for i in f), ','.join('Vec2(%g,%g)' % p for p in uv)))


def scene(instancer, extra='', material='DwaBaseMaterial("/m")', motion=False):
    return '\n'.join([
        'SceneVariables { ["image_width"]=320, ["image_height"]=200, ["pixel_samples"]=16, ["sampling_mode"]=0, ["frame"]=0, ["max_depth"]=4, '
        '["max_diffuse_depth"]=2, ["lights_visible_in_camera"]=false, ["enable_motion_blur"]=%s, ["enable_dof"]=false, ["two_stage_output"]=false, '
        '["russian_roulette_threshold"]=0, ["motion_steps"]={-0.25, 0.25} }' % ('true' if motion else 'false'),
        'PerspectiveCamera("/camera") { ["node_xform"]=%s, ["focal"]=35.0, ["film_width_aperture"]=36.0, ["near"]=0.01, ["far"]=1000.0 }' % mat(CAM),
        'SceneVariables { ["camera"]=PerspectiveCamera("/camera") }',
        'RenderOutput("/beauty") { ["file_name"]="OUTPUT", ["result"]=0, ["channel_format"]=1, ["compression"]=1 }',
        'RenderOutput("/alpha") { ["file_name"]="OUTPUT", ["result"]=1, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="A" }',
        'RenderOutput("/n") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=2, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="N" }',
        'RenderOutput("/motion") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=12, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="motion" }',
        cube('/ref'), cube('/ref2', 0.4),
        'RdlMeshGeometry("/floor") { ["vertex_list_0"]={Vec3(-6,0,6),Vec3(6,0,6),Vec3(6,0,-6),Vec3(-6,0,-6)}, ["face_vertex_count"]={4}, ["vertices_by_index"]={0,1,2,3}, ["is_subd"]=false, ["smooth_normal"]=false }',
        'CheckerboardMap("/checker") { ["num_u_tiles"]=12, ["num_v_tiles"]=12, ["color_A"]=Rgb(0.9,0.85,0.8), ["color_B"]=Rgb(0.15,0.2,0.5) }',
        'DwaBaseMaterial("/m") { ["albedo"]=bind(CheckerboardMap("/checker"), Rgb(1,1,1)), ["roughness"]=0.3, ["specular"]=1.0 }',
        'AttributeMap("/am") { ["map_type"]=0, ["primitive_attribute_name"]="inst_color", ["primitive_attribute_type"]=3, ["default_value"]=Rgb(1,0,1) }',
        'DwaBaseMaterial("/ma") { ["albedo"]=bind(AttributeMap("/am"), Rgb(1,1,1)), ["roughness"]=0.4, ["specular"]=1.0 }',
        'UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }',
        extra,
        instancer,
        'EnvLight("/fill") { ["intensity"]=0.3 }',
        'RectLight("/key") { ["node_xform"]=%s, ["width"]=3, ["height"]=2, ["intensity"]=4 }' % mat([[1, 0, 0, 0], [0, 0, -1, 0], [0, 1, 0, 0], [1.5, 4, 2, 1]]),
        'LightSet("/lights") { RectLight("/key"), EnvLight("/fill") }',
        'GeometrySet("/geometry") { RdlInstancerGeometry("/inst"), RdlMeshGeometry("/floor") }',
        'Layer("/layer") { { RdlMeshGeometry("/ref"), "", %s, LightSet("/lights") }, { RdlMeshGeometry("/ref2"), "", %s, LightSet("/lights") }, '
        '{ RdlInstancerGeometry("/inst"), "", %s, LightSet("/lights") }, '
        '{ RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") } }' % (material, material, material),
        'SceneVariables { ["layer"]=Layer("/layer") }', ''])


X = [translate(-1.4, 0, 0), mul(rot_y(30), translate(-0.4, 0, -0.3)), mul(scale(1.6, 0.6, 1), translate(0.7, 0, 0.2)),
     mul(rot_x(20), translate(1.6, 0.3, -0.6)), translate(0, 0, 1.2)]
XS = '{' + ','.join(mat(m) for m in X) + '}'
CLOSE = '{' + ','.join(mat(mul(mul(rot_y(25), m), translate(0.3, 0.05, 0))) for m in X) + '}'
cases = {
    'inst-static': scene('RdlInstancerGeometry("/inst") { ["method"]=2, ["references"]={RdlMeshGeometry("/ref")}, ["xform_list"]=%s }' % XS),
    'inst-attrs': scene('RdlInstancerGeometry("/inst") { ["method"]=2, ["references"]={RdlMeshGeometry("/ref")}, ["xform_list"]=%s, '
                        '["primitive_attributes"]={UserData("/ud")} }' % XS,
                        'UserData("/ud") { ["color_key"]="inst_color", ["color_values_0"]={Rgb(1,0.2,0.1),Rgb(0.2,1,0.2),Rgb(0.1,0.3,1),Rgb(1,1,0.2),Rgb(0.8,0.8,0.8)} }',
                        material='DwaBaseMaterial("/ma")'),
    'inst-points': scene('RdlInstancerGeometry("/inst") { ["method"]=0, ["references"]={RdlMeshGeometry("/ref"), RdlMeshGeometry("/ref2")}, '
                         '["positions"]={Vec3(-1.4,0,0),Vec3(-0.3,0,-0.4),Vec3(0.8,0,0.3),Vec3(1.7,0.2,-0.6),Vec3(0,0,1.1)}, '
                         '["orientations"]={Vec4(0,0,0,1),Vec4(0,0.258819,0,0.965926),Vec4(0,0,0,1),Vec4(0.173648,0,0,0.984808),Vec4(0,0,0,1)}, '
                         '["scales"]={Vec3(1,1,1),Vec3(1,1,1),Vec3(1.6,0.6,1),Vec3(1,1,1),Vec3(0.8,1.4,0.8)}, ["ref_indices"]={0,1,0,1,0}, ["disable_indices"]={3} }'),
    'inst-mb-close': scene('RdlInstancerGeometry("/inst") { ["method"]=2, ["references"]={RdlMeshGeometry("/ref")}, ["xform_list"]=%s, ["xform_list_close"]=%s }'
                           % (XS, CLOSE), motion=True),
    'inst-mb-velocity': scene('RdlInstancerGeometry("/inst") { ["method"]=2, ["references"]={RdlMeshGeometry("/ref")}, ["xform_list"]=%s, '
                              '["velocities"]={Vec3(6,0,0),Vec3(0,4,0),Vec3(-4,0,3),Vec3(2,2,2),Vec3(0,0,-6)} }' % XS, motion=True),
    'inst-mb-parent': scene('RdlInstancerGeometry("/inst") { ["node_xform"]=blur(%s, %s), ["method"]=2, ["references"]={RdlMeshGeometry("/ref")}, ["xform_list"]=%s }'
                            % (mat(translate(0, 0, 0)), mat(mul(rot_y(20), translate(0.4, 0, 0))), XS), motion=True),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
