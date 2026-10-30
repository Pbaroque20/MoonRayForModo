"""Emissive volumes: make_emissive_scenes.py <folder>. A glowing BaseVolume in a closed sphere mesh over a floor beside a
diffuse ball (lit by it), thin and thick, and two overlapping glows (SUM)."""
import math
import sys
from pathlib import Path

folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)


def mat(m):
    return 'Mat4(%s)' % ','.join('%.9g' % v for row in m for v in row)


def sphere(name, cx, cy, cz, r, nu=24, nv=12):
    verts, idx, counts = [], [], []
    for j in range(nv + 1):
        t = math.pi * j / nv
        for i in range(nu + 1):
            p = 2 * math.pi * i / nu
            verts.append((cx + r * math.sin(t) * math.cos(p), cy + r * math.cos(t), cz + r * math.sin(t) * math.sin(p)))
    for j in range(nv):
        for i in range(nu):
            a, b = j * (nu + 1) + i, (j + 1) * (nu + 1) + i
            idx += [a, a + 1, b + 1, b]
            counts.append(4)
    return ('RdlMeshGeometry("%s") { ["vertex_list_0"]={%s}, ["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}, ["is_subd"]=false, ["smooth_normal"]=true }'
            % (name, ','.join('Vec3(%.6g,%.6g,%.6g)' % v for v in verts), ','.join(map(str, counts)), ','.join(map(str, idx))))


CAM = [[1, 0, 0, 0], [0, 0.970296, -0.241922, 0], [0, 0.241922, 0.970296, 0], [0, 1.6, 5.2, 1]]


def scene(volumes, extra_geometry=()):
    lines = [
        'SceneVariables { ["image_width"]=320, ["image_height"]=200, ["pixel_samples"]=16, ["sampling_mode"]=0, ["frame"]=0, ["max_depth"]=4, '
        '["max_diffuse_depth"]=2, ["lights_visible_in_camera"]=false, ["enable_motion_blur"]=false, ["enable_dof"]=false, ["two_stage_output"]=false, '
        '["russian_roulette_threshold"]=0 }',
        'PerspectiveCamera("/camera") { ["node_xform"]=%s, ["focal"]=35.0, ["film_width_aperture"]=36.0, ["near"]=0.01, ["far"]=1000.0 }' % mat(CAM),
        'SceneVariables { ["camera"]=PerspectiveCamera("/camera") }',
        'RenderOutput("/beauty") { ["file_name"]="OUTPUT", ["result"]=0, ["channel_format"]=1, ["compression"]=1 }',
        'RenderOutput("/alpha") { ["file_name"]="OUTPUT", ["result"]=1, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="A" }',
        'RdlMeshGeometry("/floor") { ["vertex_list_0"]={Vec3(-6,0,6),Vec3(6,0,6),Vec3(6,0,-6),Vec3(-6,0,-6)}, ["face_vertex_count"]={4}, ["vertices_by_index"]={0,1,2,3}, ["is_subd"]=false, ["smooth_normal"]=false }',
        'UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }',
        sphere('/ball', 1.2, 0.6, 0.0, 0.6, 32, 16),
        'DwaBaseMaterial("/ball_m") { ["albedo"]=Rgb(0.8,0.8,0.8), ["roughness"]=0.4, ["specular"]=1.0 }',
        'EnvLight("/fill") { ["intensity"]=0.05 }',
        'LightSet("/lights") { EnvLight("/fill") }',
    ]
    entries = ['{ RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") }',
               '{ RdlMeshGeometry("/ball"), "", DwaBaseMaterial("/ball_m"), LightSet("/lights") }']
    geoms = ['RdlMeshGeometry("/floor")', 'RdlMeshGeometry("/ball")']
    for name, center, radius, shader in volumes:
        lines.append(sphere(name, *center, radius))
        lines.append(shader)
        shader_ref = shader[:shader.index(')') + 1]
        entries.append('{ RdlMeshGeometry("%s"), "", LightSet("/lights"), %s }' % (name, shader_ref))
        geoms.append('RdlMeshGeometry("%s")' % name)
    lines += ['GeometrySet("/geometry") { %s }' % ', '.join(geoms), 'Layer("/layer") { %s }' % ', '.join(entries),
              'SceneVariables { ["layer"]=Layer("/layer") }', '']
    return '\n'.join(lines)


GLOW = 'BaseVolume("/glow") { ["emission_color"]=Rgb(1.0,0.55,0.2), ["emission_intensity"]=4.0, ["attenuation_color"]=Rgb(1,1,1), ["attenuation_intensity"]=0.5, ["diffuse_color"]=Rgb(0.8,0.8,0.8) }'
THICK = 'BaseVolume("/thick") { ["emission_color"]=Rgb(0.3,0.6,1.0), ["emission_intensity"]=3.0, ["attenuation_color"]=Rgb(1,1,1), ["attenuation_intensity"]=4.0, ["diffuse_color"]=Rgb(0.7,0.7,0.7) }'
cases = {
    'emit-thin': scene([('/v1', (-0.4, 0.8, 0.0), 0.7, GLOW)]),
    'emit-thick': scene([('/v1', (-0.4, 0.8, 0.0), 0.7, THICK)]),
    'emit-two': scene([('/v1', (-0.6, 0.8, 0.0), 0.6, GLOW), ('/v2', (0.1, 0.9, -0.2), 0.5, THICK)]),
}
for name, text in cases.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(len(cases), 'cases')
