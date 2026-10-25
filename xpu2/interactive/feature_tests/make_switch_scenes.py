"""The kit's MoonRay source switches: make_switch_scenes.py <folder>. Textures of one, two and three channels (grey,
grey and alpha, colour without alpha) as colour and as alpha (alpha_only into presence), a mirror smooth glass with
an independent rough transmission, and toon materials on a coarse smooth-shaded sphere lit across its terminator,
with the albedo AOV. Run each with the switches off (MoonRay's source) and on (the kit's defaults)."""
import math
import subprocess
import sys
from pathlib import Path

folder = Path(sys.argv[1]).resolve()
folder.mkdir(parents=True, exist_ok=True)
RT = Path(r'C:\Users\Raphael Tobar\AppData\Roaming\Luxology\Kits\MoonRayForModo\runtime')
OIIO, MAKETX = RT / 'oiiotool.exe', RT / 'maketx.exe'
env = {'PATH': str(RT), 'SYSTEMROOT': r'C:\Windows'}
tex = folder / 'tex'
tex.mkdir(exist_ok=True)


def run(args):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, env=env)
    if r.returncode:
        raise SystemExit(r.stdout + r.stderr)


# Grey checker (1 channel), grey with a soft alpha disc (2 channels, alpha channel 1), colour stripes (3 channels).
run([OIIO, '--pattern', 'checker:width=32:height=32:color1=0.9:color2=0.1', '256x256', '1', '-d', 'uint8', '-o', tex / 'gray.tif'])
run([OIIO, '--pattern', 'checker:width=32:height=32:color1=0.8:color2=0.3', '256x256', '1', '--pattern', 'fill:topleft=1:topright=0:bottomleft=0:bottomright=1',
     '256x256', '1', '--chappend', '--chnames', 'Y,A', '-d', 'uint8', '-o', tex / 'gray_alpha.tif'])
run([OIIO, '--pattern', 'checker:width=64:height=16:color1=0.9,0.3,0.1:color2=0.1,0.4,0.8', '256x256', '3', '-d', 'uint8', '-o', tex / 'rgb.tif'])
for name in ('gray', 'gray_alpha', 'rgb'):
    run([MAKETX, '--oiio', tex / (name + '.tif'), '-o', tex / (name + '.tx')])


def mat(m):
    return 'Mat4(%s)' % ','.join('%.9g' % v for row in m for v in row)


def sphere(name, cx, cy, cz, r, nu, nv, smooth=True):
    verts, idx, counts, uvs = [], [], [], []
    for j in range(nv + 1):
        t = math.pi * j / nv
        for i in range(nu + 1):
            p = 2 * math.pi * i / nu
            verts.append((cx + r * math.sin(t) * math.cos(p), cy + r * math.cos(t), cz + r * math.sin(t) * math.sin(p)))
            uvs.append((i / nu, 1 - j / nv))
    for j in range(nv):
        for i in range(nu):
            a, b = j * (nu + 1) + i, (j + 1) * (nu + 1) + i
            idx += [a, a + 1, b + 1, b]
            counts.append(4)
    return ('RdlMeshGeometry("%s") { ["vertex_list_0"]={%s}, ["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}, ["uv_list"]={%s}, '
            '["is_subd"]=false, ["smooth_normal"]=%s }' % (name, ','.join('Vec3(%.6g,%.6g,%.6g)' % v for v in verts), ','.join(map(str, counts)),
                                                       ','.join(map(str, idx)), ','.join('Vec2(%.6g,%.6g)' % u for u in uvs), 'true' if smooth else 'false'))


CAM = [[1, 0, 0, 0], [0, 0.970296, -0.241922, 0], [0, 0.241922, 0.970296, 0], [0, 1.6, 5.2, 1]]


def scene(materials, assignments, key=(3.5, 1.4, 0.4), albedo=False):
    lines = [
        'SceneVariables { ["image_width"]=320, ["image_height"]=200, ["pixel_samples"]=16, ["sampling_mode"]=0, ["frame"]=0, ["max_depth"]=4, '
        '["max_diffuse_depth"]=2, ["lights_visible_in_camera"]=false, ["enable_motion_blur"]=false, ["enable_dof"]=false, ["two_stage_output"]=false, '
        '["russian_roulette_threshold"]=0 }',
        'PerspectiveCamera("/camera") { ["node_xform"]=%s, ["focal"]=35.0, ["film_width_aperture"]=36.0, ["near"]=0.01, ["far"]=1000.0 }' % mat(CAM),
        'SceneVariables { ["camera"]=PerspectiveCamera("/camera") }',
        'RenderOutput("/beauty") { ["file_name"]="OUTPUT", ["result"]=0, ["channel_format"]=1, ["compression"]=1 }',
        'RenderOutput("/alpha") { ["file_name"]="OUTPUT", ["result"]=1, ["channel_format"]=1, ["compression"]=1, ["channel_name"]="A" }',
    ]
    if albedo:
        lines.append('RenderOutput("/albedo") { ["file_name"]="OUTPUT", ["result"]=7, ["material_aov"]="albedo", ["channel_format"]=1, ["compression"]=1, ["channel_name"]="albedo" }')
    lines += [
        sphere('/a', -1.3, 0.75, 0, 0.7, 16, 8), sphere('/b', 0, 0.75, 0, 0.7, 16, 8), sphere('/c', 1.3, 0.75, 0, 0.7, 16, 8),
        'RdlMeshGeometry("/floor") { ["vertex_list_0"]={Vec3(-6,0,6),Vec3(6,0,6),Vec3(6,0,-6),Vec3(-6,0,-6)}, ["face_vertex_count"]={4}, ["vertices_by_index"]={0,1,2,3}, ["uv_list"]={Vec2(0,0),Vec2(6,0),Vec2(6,6),Vec2(0,6)}, ["is_subd"]=false, ["smooth_normal"]=false }',
        'UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }',
    ] + materials + [
        'EnvLight("/fill") { ["intensity"]=0.25 }',
        'RectLight("/key") { ["node_xform"]=%s, ["width"]=1.2, ["height"]=1.2, ["intensity"]=12 }' % mat(look_at(key)),
        'LightSet("/lights") { RectLight("/key"), EnvLight("/fill") }',
        'GeometrySet("/geometry") { RdlMeshGeometry("/a"), RdlMeshGeometry("/b"), RdlMeshGeometry("/c"), RdlMeshGeometry("/floor") }',
        'Layer("/layer") { %s, { RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") } }'
        % ', '.join('{ RdlMeshGeometry("/%s"), "", %s, LightSet("/lights") }' % (g, m) for g, m in assignments),
        'SceneVariables { ["layer"]=Layer("/layer") }', '']
    return '\n'.join(lines)


def look_at(pos, target=(0, 0.75, 0)):
    # A rect light faces its -z: its z axis points from the target to it.
    z = [pos[i] - target[i] for i in range(3)]
    l = math.sqrt(sum(v * v for v in z))
    z = [v / l for v in z]
    up = [0, 1, 0]
    x = [up[1] * z[2] - up[2] * z[1], up[2] * z[0] - up[0] * z[2], up[0] * z[1] - up[1] * z[0]]
    l = math.sqrt(sum(v * v for v in x))
    x = [v / l for v in x]
    y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
    return [x + [0], y + [0], z + [0], list(pos) + [1]]


T = tex.as_posix()
textures = scene([
    'ImageMap("/gray") { ["texture"]="%s/gray.tx" }' % T,
    'ImageMap("/ga") { ["texture"]="%s/gray_alpha.tx" }' % T,
    'ImageMap("/ga_alpha") { ["texture"]="%s/gray_alpha.tx", ["alpha_only"]=true }' % T,
    'ImageMap("/rgb") { ["texture"]="%s/rgb.tx" }' % T,
    'ImageMap("/rgb_alpha") { ["texture"]="%s/rgb.tx", ["alpha_only"]=true }' % T,
    'DwaBaseMaterial("/ma") { ["albedo"]=bind(ImageMap("/gray"), Rgb(1,1,1)), ["roughness"]=0.4 }',
    'DwaBaseMaterial("/mb") { ["albedo"]=bind(ImageMap("/ga"), Rgb(1,1,1)), ["presence"]=bind(ImageMap("/ga_alpha"), 1.0), ["roughness"]=0.4 }',
    'DwaBaseMaterial("/mc") { ["albedo"]=bind(ImageMap("/rgb"), Rgb(1,1,1)), ["presence"]=bind(ImageMap("/rgb_alpha"), 1.0), ["roughness"]=0.4 }',
], [('a', 'DwaBaseMaterial("/ma")'), ('b', 'DwaBaseMaterial("/mb")'), ('c', 'DwaBaseMaterial("/mc")')])
glass = scene([
    'DwaBaseMaterial("/ga") { ["albedo"]=Rgb(1,1,1), ["roughness"]=0, ["specular"]=1, ["transmission"]=1, ["refractive_index"]=1.45, '
    '["use_independent_transmission_roughness"]=true, ["independent_transmission_roughness"]=0.45 }',
    'DwaBaseMaterial("/gb") { ["albedo"]=Rgb(1,1,1), ["roughness"]=0, ["specular"]=1, ["transmission"]=1, ["refractive_index"]=1.45, '
    '["use_independent_transmission_roughness"]=true, ["independent_transmission_roughness"]=0.15, ["transmission_color"]=Rgb(0.8,0.95,0.85) }',
    'DwaBaseMaterial("/gc") { ["albedo"]=Rgb(1,1,1), ["roughness"]=0, ["specular"]=1, ["transmission"]=1, ["refractive_index"]=1.45 }',
], [('a', 'DwaBaseMaterial("/ga")'), ('b', 'DwaBaseMaterial("/gb")'), ('c', 'DwaBaseMaterial("/gc")')])
toon = scene([
    'DwaToonMaterial("/ta") { ["albedo"]=Rgb(0.85,0.35,0.2), ["diffuse_model"]=1, ["positions"]={0.0, 0.45, 0.55, 1.0}, '
    '["colors"]={Rgb(1,1,1), Rgb(1,1,1), Rgb(0.35,0.35,0.35), Rgb(0.2,0.2,0.2)}, ["interpolations"]={1, 1, 1, 1}, ["specular"]=0 }',
    'DwaToonMaterial("/tb") { ["albedo"]=Rgb(0.3,0.6,0.85), ["diffuse_model"]=1, ["extend_ramp"]=true, ["ramp_input_scale"]=0.8, ["specular"]=0 }',
    'DwaBaseMaterial("/tc") { ["albedo"]=Rgb(0.6,0.6,0.6), ["roughness"]=0.5 }',
], [('a', 'DwaToonMaterial("/ta")'), ('b', 'DwaToonMaterial("/tb")'), ('c', 'DwaBaseMaterial("/tc")')], key=(3.2, 0.9, -1.2), albedo=True)
for name, text in {'sw-textures': textures, 'sw-glass': glass, 'sw-toon': toon}.items():
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print('3 cases')
