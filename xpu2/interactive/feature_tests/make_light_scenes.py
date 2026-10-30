"""Light test scenes for XPU2 against MoonRay: make_light_scenes.py <folder> <texture.tx> <hdri.tx> <pixel samples>.
Writes <case>.rdla for each case; outputs go to <folder>/<case>-<renderer>.exr (the harness rewrites the suffix)."""
import sys
from pathlib import Path

folder, tex, hdri, samples = Path(sys.argv[1]).resolve(), sys.argv[2].replace('\\', '/'), sys.argv[3].replace('\\', '/'), int(sys.argv[4])

BASE = '''SceneVariables { ["image_width"]=320, ["image_height"]=200, ["pixel_samples"]=%d, ["sampling_mode"]=0, ["frame"]=0, ["max_depth"]=4, ["max_diffuse_depth"]=2, ["lights_visible_in_camera"]=false, ["enable_motion_blur"]=false, ["enable_dof"]=false, ["two_stage_output"]=false }
PerspectiveCamera("/camera") { ["node_xform"]=Mat4(1,0,0,0, 0,0.978148,-0.207912,0, 0,0.207912,0.978148,0, 0,2.0,7.5,1), ["focal"]=35.0, ["film_width_aperture"]=36.0, ["near"]=0.01, ["far"]=1000.0 }
SceneVariables { ["camera"]=PerspectiveCamera("/camera") }
RenderOutput("/beauty") { ["file_name"]="OUTPUT", ["result"]=0, ["channel_format"]=0, ["compression"]=1 }
UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.5,0.5,0.5), ["useSpecularWorkflow"]=1 }
DwaBaseMaterial("/ball_m") { ["albedo"]=Rgb(0.7,0.7,0.7), ["roughness"]=0.25 }
DwaBaseMaterial("/mirror_m") { ["metallic"]=1, ["metallic_color"]=Rgb(0.95,0.95,0.95), ["roughness"]=0.05 }
RdlMeshGeometry("/floor") { ["vertex_list"]={Vec3(-8,0,5),Vec3(8,0,5),Vec3(8,0,-6),Vec3(-8,0,-6)}, ["face_vertex_count"]={4}, ["vertices_by_index"]={0,1,2,3}, ["is_subd"]=false, ["smooth_normal"]=false }
RdlMeshGeometry("/wall") { ["vertex_list"]={Vec3(-8,0,-3),Vec3(8,0,-3),Vec3(8,6,-3),Vec3(-8,6,-3)}, ["face_vertex_count"]={4}, ["vertices_by_index"]={0,1,2,3}, ["is_subd"]=false, ["smooth_normal"]=false }
''' % samples


def sphere(name, cx, cy, cz, r, seg=24, band=16):
    import math
    v = []
    for b in range(band + 1):
        t = math.pi * b / band
        for s in range(seg):
            p = 2 * math.pi * s / seg
            v.append((cx + r * math.sin(t) * math.cos(p), cy + r * math.cos(t), cz + r * math.sin(t) * math.sin(p)))
    f = []
    for b in range(band):
        for s in range(seg):
            a, c = b * seg + s, b * seg + (s + 1) % seg
            f.append((a, c, c + seg, a + seg))
    return 'RdlMeshGeometry("%s") { ["vertex_list"]={%s}, ["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}, ["is_subd"]=false, ["smooth_normal"]=true }\n' % (
        name, ','.join('Vec3(%.5f,%.5f,%.5f)' % q for q in v), ','.join('4' for _ in f), ','.join(str(i) for q in f for i in q))


GEOM = sphere('/ball', -1.2, 1.0, 0.0, 1.0) + sphere('/mirror', 1.4, 0.8, 0.5, 0.8)
LAYER = '''GeometrySet("/geometry") { RdlMeshGeometry("/floor"),RdlMeshGeometry("/wall"),RdlMeshGeometry("/ball"),RdlMeshGeometry("/mirror") }
Layer("/layer") { { RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") },{ RdlMeshGeometry("/wall"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") },{ RdlMeshGeometry("/ball"), "", DwaBaseMaterial("/ball_m"), LightSet("/lights") },{ RdlMeshGeometry("/mirror"), "", DwaBaseMaterial("/mirror_m"), LightSet("/lights") } }
SceneVariables { ["layer"]=Layer("/layer") }
'''
FILL = 'EnvLight("/fill") { ["intensity"]=0.05 }\n'
CASES = {
    'rect-texture-spread': FILL + 'RectLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 0,4.5,1,1), ["width"]=3, ["height"]=2, ["intensity"]=3, ["spread"]=0.45, ["texture"]="%s", ["texture_filter"]=1, ["visible_in_camera"]=1 }\n' % tex,
    'disk-texture-spread': FILL + 'DiskLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 0,4.5,1,1), ["radius"]=1.5, ["intensity"]=3, ["spread"]=0.5, ["texture"]="%s", ["visible_in_camera"]=1 }\n' % tex,
    'sphere-texture': FILL + 'SphereLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,3.6,1.5,1), ["radius"]=0.6, ["intensity"]=4, ["texture"]="%s", ["texture_filter"]=1, ["visible_in_camera"]=1 }\n' % tex,
    'spot-texture': FILL + 'SpotLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 0,5,0.5,1), ["lens_radius"]=0.4, ["outer_cone_angle"]=70, ["inner_cone_angle"]=40, ["intensity"]=40, ["texture"]="%s", ["texture_filter"]=1, ["visible_in_camera"]=1, ["black_level"]=0.05 }\n' % tex,
    'distant-texture-mip': FILL + 'DistantLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0.5,-0.866025,0, 0,0.866025,0.5,0, 0,0,0,1), ["angular_extent"]=20, ["intensity"]=2, ["texture"]="%s", ["texture_filter"]=3 }\n' % tex,
    'env-hdri': 'EnvLight("/env") { ["texture"]="%s", ["texture_filter"]=1, ["visible_in_camera"]=1, ["intensity"]=1 }\n' % hdri,
    'env-hdri-controls': 'EnvLight("/env") { ["node_xform"]=Mat4(0.866025,0,-0.5,0, 0,1,0,0, 0.5,0,0.866025,0, 0,0,0,1), ["texture"]="%s", ["texture_filter"]=3, ["visible_in_camera"]=1, ["gamma"]=Rgb(1.2,1.0,0.9), ["saturation"]=Rgb(0.6,0.6,0.6), ["gain"]=Rgb(1.1,1.0,1.0), ["texture_rotation"]=15, ["texture_reps_u"]=2, ["texture_mirror_u"]=true }\n' % hdri,
    'env-hemisphere': 'EnvLight("/env") { ["texture"]="%s", ["texture_filter"]=0, ["visible_in_camera"]=1, ["sample_upper_hemisphere_only"]=true }\n' % hdri,
}
for name, light in CASES.items():
    lights = [l.split('(')[0] + '("' + l.split('"')[1] + '")' for l in light.strip().split('\n')]
    text = BASE + light + 'LightSet("/lights") { %s }\n' % ', '.join(lights) + GEOM + LAYER
    (folder / (name + '.rdla')).write_text(text, encoding='utf-8')
print(' '.join(CASES))
