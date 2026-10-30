"""Subdivision surface test scenes: make_subd_scenes.py <folder>. Subdivided cubes and an open grid under a rect light,
with face-varying UVs, creases, corners, parts, reversed normals, uniform and camera-adaptive tessellation, both
schemes and every boundary mode, and a textured checker to show the UVs and their derivatives."""
import sys
from pathlib import Path

folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)


def cube(size=1.0, center=(0, 1, 0)):
    s = size / 2
    cx, cy, cz = center
    v = [(cx + x * s, cy + y * s, cz + z * s) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    # Faces wound outward.
    faces = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
    uv = []
    for fi, f in enumerate(faces):
        u0, v0 = (fi % 3) / 3.0, (fi // 3) / 2.0
        uv += [(u0 + 0.02, v0 + 0.02), (u0 + 0.31, v0 + 0.02), (u0 + 0.31, v0 + 0.48), (u0 + 0.02, v0 + 0.48)]
    return v, faces, uv


def grid(n=4, size=3.0, center=(0, 0.6, 0)):
    cx, cy, cz = center
    v = [(cx - size / 2 + size * i / n, cy + 0.3 * ((i + j) % 2), cz - size / 2 + size * j / n) for j in range(n + 1) for i in range(n + 1)]
    faces = [(j * (n + 1) + i, (j + 1) * (n + 1) + i, (j + 1) * (n + 1) + i + 1, j * (n + 1) + i + 1) for j in range(n) for i in range(n)]
    uv = [(i / n, j / n) for j in range(n + 1) for i in range(n + 1)]
    return v, faces, uv


def mesh(name, v, faces, uv, uv_per_corner, extra=''):
    counts = ','.join(str(len(f)) for f in faces)
    idx = ','.join(str(i) for f in faces for i in f)
    vl = '{' + ','.join('Vec3(%g,%g,%g)' % p for p in v) + '}'
    ul = '{' + ','.join('Vec2(%g,%g)' % p for p in uv) + '}'
    return ('RdlMeshGeometry("%s") { ["vertex_list"]=%s, ["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}, ["uv_list"]=%s, ["is_subd"]=true%s }'
            % (name, vl, counts, idx, ul, extra))


def scene(geometry, materials, layer, camera_z=6.0):
    return '\n'.join([
        'SceneVariables { ["image_width"]=320, ["image_height"]=200, ["pixel_samples"]=16, ["sampling_mode"]=0, ["frame"]=0, ["max_depth"]=4, '
        '["max_diffuse_depth"]=2, ["lights_visible_in_camera"]=false, ["enable_motion_blur"]=false, ["enable_dof"]=false, ["two_stage_output"]=false, '
        '["russian_roulette_threshold"]=0 }',
        'PerspectiveCamera("/camera") { ["node_xform"]=Mat4(1,0,0,0, 0,0.970296,-0.241922,0, 0,0.241922,0.970296,0, 0,2.2,%g,1), ["focal"]=35.0, ["film_width_aperture"]=36.0, ["near"]=0.01, ["far"]=1000.0 }' % camera_z,
        'SceneVariables { ["camera"]=PerspectiveCamera("/camera") }',
        'RenderOutput("/beauty") { ["file_name"]="OUTPUT", ["result"]=0, ["channel_format"]=1, ["compression"]=1 }',
        'RenderOutput("/alpha") { ["file_name"]="OUTPUT", ["result"]=1, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="A" }',
        'RenderOutput("/depth") { ["file_name"]="OUTPUT", ["result"]=2, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="Z" }',
        'RenderOutput("/n") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=2, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="N" }',
        'RenderOutput("/st") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=3, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="St" }',
        'RenderOutput("/dpds") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=4, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="dPds" }',
        'RenderOutput("/dsdx") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=6, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="dSdx" }',
        geometry,
        'RdlMeshGeometry("/floor") { ["vertex_list"]={Vec3(-6,0,6),Vec3(6,0,6),Vec3(6,0,-6),Vec3(-6,0,-6)}, ["face_vertex_count"]={4}, ["vertices_by_index"]={0,1,2,3}, ["is_subd"]=false, ["smooth_normal"]=false }',
        'CheckerboardMap("/checker") { ["num_u_tiles"]=12, ["num_v_tiles"]=12, ["color_A"]=Rgb(0.9,0.85,0.8), ["color_B"]=Rgb(0.15,0.2,0.5) }',
        materials,
        'UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }',
        'EnvLight("/fill") { ["intensity"]=0.3 }',
        'RectLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 1.5,4,2,1), ["width"]=3, ["height"]=2, ["intensity"]=4 }',
        'LightSet("/lights") { RectLight("/key"), EnvLight("/fill") }',
        'GeometrySet("/geometry") { RdlMeshGeometry("/s"),RdlMeshGeometry("/floor") }',
        layer,
        'SceneVariables { ["layer"]=Layer("/layer") }', ''])


DWA = 'DwaBaseMaterial("/subd_m") { ["albedo"]=bind(CheckerboardMap("/checker"), Rgb(1,1,1)), ["roughness"]=0.3, ["specular"]=1.0 }'
DWA2 = 'DwaBaseMaterial("/subd_m2") { ["albedo"]=Rgb(0.8,0.3,0.2), ["roughness"]=0.5, ["metallic"]=0 }'


def layer(entries):
    return 'Layer("/layer") { ' + ','.join('{ RdlMeshGeometry("%s"), "%s", %s, LightSet("/lights") }' % e for e in entries) + \
        ',{ RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") } }'


cases = {}
v, f, uv = cube()
# Face-varying UVs (a corner each), uniform tessellation.
cases['subd-cube'] = scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=8'), DWA, layer([('/s', '', 'DwaBaseMaterial("/subd_m")')]))
# Creases, corners and the control cage's resolution (1: no tessellation).
cases['subd-crease'] = scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=6, ["subd_crease_indices"]={0,1,1,3,4,5}, ["subd_crease_sharpnesses"]={3.0,10.0,2.0}, '
                                  '["subd_corner_indices"]={6,7}, ["subd_corner_sharpnesses"]={4.0,1.5}'), DWA, layer([('/s', '', 'DwaBaseMaterial("/subd_m")')]))
cases['subd-cage'] = scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=1'), DWA, layer([('/s', '', 'DwaBaseMaterial("/subd_m")')]))
# Camera-adaptive tessellation.
cases['subd-adaptive'] = scene(mesh('/s', v, f, uv, True, ', ["adaptive_error"]=2.0, ["mesh_resolution"]=16'), DWA, layer([('/s', '', 'DwaBaseMaterial("/subd_m")')]))
# Parts with two materials, reversed normals, bilinear scheme.
cases['subd-parts'] = scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=6, ["part_list"]={"top","rest"}, ["part_face_count_list"]={2,4}, ["part_face_indices"]={3,1,0,2,4,5}'),
                            DWA + '\n' + DWA2, layer([('/s', 'top', 'DwaBaseMaterial("/subd_m2")'), ('/s', 'rest', 'DwaBaseMaterial("/subd_m")')]))
cases['subd-reversed'] = scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=6, ["reverse_normals"]=true'), DWA, layer([('/s', '', 'DwaBaseMaterial("/subd_m")')]))
cases['subd-bilinear'] = scene(mesh('/s', v, f, uv, True, ', ["mesh_resolution"]=6, ["subd_scheme"]=0'), DWA, layer([('/s', '', 'DwaBaseMaterial("/subd_m")')]))
# An open grid with each boundary interpolation and per-vertex UVs.
gv, gf, guv = grid()
for b in range(3):
    for fv in (1, 4):
        cases['subd-grid-b%d-f%d' % (b, fv)] = scene(mesh('/s', gv, gf, guv, False, ', ["mesh_resolution"]=6, ["subd_boundary"]=%d, ["subd_fvar_linear"]=%d' % (b, fv)),
                                                     DWA, layer([('/s', '', 'DwaBaseMaterial("/subd_m")')]))
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
