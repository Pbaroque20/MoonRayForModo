"""Bake camera test scenes: make_bake_scenes.py <folder>. A UV sphere (quads, triangles at the poles) on a floor under a
rect light, baked through MoonRay's BakeCamera in each mode, as a triangle mesh, in another UDIM tile and from a
primitive attribute's coordinates."""
import math
import sys
from pathlib import Path

folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)


def sphere(rings=12, segments=24, triangles=False, shift=(0.0, 0.0)):
    verts, uvs, normals, counts, indices = [], [], [], [], []
    for j in range(rings + 1):
        lat = -math.pi / 2 + math.pi * j / rings
        for i in range(segments + 1):
            lon = 2 * math.pi * i / segments
            n = (math.cos(lat) * math.cos(lon), math.sin(lat), math.cos(lat) * math.sin(lon))
            verts.append(n)
            normals.append(n)
            uvs.append((i / segments + shift[0], j / rings + shift[1]))
    row = segments + 1
    for j in range(rings):
        for i in range(segments):
            a, b, c, d = j * row + i, j * row + i + 1, (j + 1) * row + i + 1, (j + 1) * row + i
            if j == 0:
                face = [a, c, d]  # the south pole: a triangle
            elif j == rings - 1:
                face = [a, b, c]  # the north pole
            else:
                face = [a, b, c, d]
            # Faces wind so their normals face out (counterclockwise seen from outside).
            face = face[::-1]
            if triangles and len(face) == 4:
                counts += [3, 3]
                indices += [face[0], face[1], face[2], face[0], face[2], face[3]]
            else:
                counts.append(len(face))
                indices += face
    return verts, uvs, normals, counts, indices


def vec3(vs):
    return '{' + ','.join('Vec3(%.6f,%.6f,%.6f)' % v for v in vs) + '}'


def vec2(vs):
    return '{' + ','.join('Vec2(%.6f,%.6f)' % v for v in vs) + '}'


def scene(mode=3, triangles=False, udim=1001, shift=(0.0, 0.0), uv_attribute='', map_factor=1.0, bias=None, camera_at=(0, 1, 5)):
    verts, uvs, normals, counts, indices = sphere(triangles=triangles, shift=shift)
    extra = ''
    prim = ''
    if uv_attribute:
        flipped = [(u, 1.0 - v) for u, v in uvs]
        extra = 'UserData("/bakeuv") { ["vec2f_key"]="%s", ["vec2f_values_0"]=%s }\n' % (uv_attribute, vec2(flipped))
        prim = ', ["primitive_attributes"]={UserData("/bakeuv")}'
    cam = 'BakeCamera("/bake") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, %g,%g,%g,1), ["geometry"]=RdlMeshGeometry("/ball"), ["mode"]=%d, ["udim"]=%d, ["map_factor"]=%g, ["normal_map"]="modo-no-normal-map"%s%s, ["near"]=0.0001 }' % (
        camera_at[0], camera_at[1], camera_at[2], mode, udim, map_factor,
        ', ["uv_attribute"]="%s"' % uv_attribute if uv_attribute else '', ', ["bias"]=%g' % bias if bias is not None else '')
    return '\n'.join([
        'SceneVariables { ["image_width"]=128, ["image_height"]=128, ["pixel_samples"]=16, ["sampling_mode"]=0, ["frame"]=0, ["max_depth"]=4, ["max_diffuse_depth"]=2, '
        '["lights_visible_in_camera"]=false, ["enable_motion_blur"]=false, ["enable_dof"]=false, ["two_stage_output"]=false, ["russian_roulette_threshold"]=0 }',
        cam,
        'SceneVariables { ["camera"]=BakeCamera("/bake") }',
        'RenderOutput("/beauty") { ["file_name"]="OUTPUT", ["result"]=0, ["channel_format"]=1, ["compression"]=1 }',
        'RenderOutput("/alpha") { ["file_name"]="OUTPUT", ["result"]=1, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="A" }',
        'RenderOutput("/depth") { ["file_name"]="OUTPUT", ["result"]=2, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="Z" }',
        'RenderOutput("/wp") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=10, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="Wp" }',
        'RenderOutput("/n") { ["file_name"]="OUTPUT", ["result"]=3, ["state_variable"]=2, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="N" }',
        extra +
        'RdlMeshGeometry("/ball") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,1,0,1), ["vertex_list"]=%s, ["uv_list"]=%s, ["normal_list"]=%s, '
        '["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}, ["is_subd"]=false, ["smooth_normal"]=true%s }' % (
            vec3(verts), vec2(uvs), vec3(normals), ','.join(map(str, counts)), ','.join(map(str, indices)), prim),
        'RdlMeshGeometry("/floor") { ["vertex_list"]={Vec3(-6,0,6),Vec3(6,0,6),Vec3(6,0,-6),Vec3(-6,0,-6)}, ["face_vertex_count"]={4}, ["vertices_by_index"]={0,1,2,3}, ["is_subd"]=false, ["smooth_normal"]=false }',
        'DwaBaseMaterial("/ball_m") { ["albedo"]=Rgb(0.7,0.3,0.2), ["roughness"]=0.35 }',
        'UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }',
        'EnvLight("/fill") { ["intensity"]=0.3 }',
        'RectLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 1,4,1,1), ["width"]=3, ["height"]=2, ["intensity"]=4 }',
        'LightSet("/lights") { RectLight("/key"), EnvLight("/fill") }',
        'GeometrySet("/geometry") { RdlMeshGeometry("/ball"),RdlMeshGeometry("/floor") }',
        'Layer("/layer") { { RdlMeshGeometry("/ball"), "", DwaBaseMaterial("/ball_m"), LightSet("/lights") },{ RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") } }',
        'SceneVariables { ["layer"]=Layer("/layer") }', ''])


cases = {
    'bake-m3': scene(),
    'bake-m0': scene(mode=0),
    'bake-m1': scene(mode=1, bias=0.01),
    'bake-m2': scene(mode=2, camera_at=(0, 3, 5)),
    'bake-tri': scene(triangles=True),
    'bake-udim': scene(udim=1002, shift=(1.0, 0.0), map_factor=0.5),
    'bake-uvattr': scene(uv_attribute='bakeuv'),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
