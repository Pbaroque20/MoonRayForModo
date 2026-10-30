"""A scene of polygon meshes as Modo sends them, for comparing XPU2's split with MoonRay's:
make_polygon_scene.py <out.rdla> <pixel samples> <output exr>.

- a wavy patch of non-planar quads, smooth normals (MoonRay: a QuadMesh, normals summed per quad);
- a sphere of quads with triangle fans at its poles (a QuadMesh, its triangles as v0 v1 v2 v2);
- a hexagonal prism (two hexagon caps: a TriMesh, the caps ear-clipped, the sides fanned), smooth normals;
- a flat concave ten-pointed star (a TriMesh, ear-clipped), uv per face-vertex."""
import math
import sys

out, samples, exr = sys.argv[1], int(sys.argv[2]), sys.argv[3]


def mesh(name, verts, faces, smooth=True, uvs=None):
    v = ','.join('Vec3(%.6f,%.6f,%.6f)' % p for p in verts)
    counts = ','.join(str(len(f)) for f in faces)
    idx = ','.join(str(i) for f in faces for i in f)
    text = 'RdlMeshGeometry("%s") { ["vertex_list"]={%s}, ["face_vertex_count"]={%s}, ["vertices_by_index"]={%s}, ["is_subd"]=false, ["smooth_normal"]=%s' % (
        name, v, counts, idx, 'true' if smooth else 'false')
    if uvs:
        text += ', ["uv_list"]={%s}' % ','.join('Vec2(%.6f,%.6f)' % u for u in uvs)
    return text + ' }\n'


# The wavy patch: 6 x 6 quads, z waves so no quad is planar.
n = 6
patch_v = [(-3.4 + 1.2 * i / n, 0.3 + 1.2 * j / n, 0.6 + 0.25 * math.sin(2.7 * i / n * math.pi) * math.cos(1.9 * j / n * math.pi))
           for j in range(n + 1) for i in range(n + 1)]
patch_f = [(j * (n + 1) + i, j * (n + 1) + i + 1, (j + 1) * (n + 1) + i + 1, (j + 1) * (n + 1) + i) for j in range(n) for i in range(n)]
patch_uv = [((i / n), (j / n)) for j in range(n + 1) for i in range(n + 1)]

# The sphere: 10 bands of 12 quads, triangle fans at the poles.
seg, band, r, cx = 12, 10, 0.65, -0.9
sphere_v = [(cx, 0.65 + r, 0.0)]
for b in range(1, band):
    t = math.pi * b / band
    for s in range(seg):
        p = 2 * math.pi * s / seg
        sphere_v.append((cx + r * math.sin(t) * math.cos(p), 0.65 + r * math.cos(t), r * math.sin(t) * math.sin(p)))
sphere_v.append((cx, 0.65 - r, 0.0))
sphere_f = [(0, 1 + (s + 1) % seg, 1 + s) for s in range(seg)]
for b in range(band - 2):
    for s in range(seg):
        a, c = 1 + b * seg + s, 1 + b * seg + (s + 1) % seg
        sphere_f.append((a, c, c + seg, a + seg))
last = len(sphere_v) - 1
sphere_f += [(last, 1 + (band - 2) * seg + s, 1 + (band - 2) * seg + (s + 1) % seg) for s in range(seg)]

# The prism: hexagon caps (n-gons above four vertices) and quad sides.
hx, hz, hr = 0.8, 0.2, 0.55
ring = [(hx + hr * math.cos(2 * math.pi * k / 6), hz + hr * math.sin(2 * math.pi * k / 6)) for k in range(6)]
prism_v = [(x, 0.05, z) for x, z in ring] + [(x, 1.15, z) for x, z in ring]
prism_f = [tuple(range(5, -1, -1)), tuple(range(6, 12))] + [(k, (k + 1) % 6, 6 + (k + 1) % 6, 6 + k) for k in range(6)]

# The star: ten points, concave, flat, standing up; uv per face-vertex.
star_v, star_uv = [], []
for k in range(10):
    a = math.pi / 2 + 2 * math.pi * k / 10
    rr = 0.75 if k % 2 == 0 else 0.32
    star_v.append((2.4 + rr * math.cos(a), 0.9 + rr * math.sin(a), 0.1))
    star_uv.append((0.5 + 0.5 * math.cos(a) * rr / 0.75, 0.5 + 0.5 * math.sin(a) * rr / 0.75))
star_f = [tuple(range(10))]

floor = 'RdlMeshGeometry("/floor") { ["vertex_list"]={Vec3(-8,0,4),Vec3(8,0,4),Vec3(8,0,-6),Vec3(-8,0,-6)}, ["face_vertex_count"]={4}, ["vertices_by_index"]={0,1,2,3}, ["is_subd"]=false, ["smooth_normal"]=false }\n'
scene = '''SceneVariables { ["image_width"]=360, ["image_height"]=200, ["pixel_samples"]=%d, ["sampling_mode"]=0, ["frame"]=0, ["max_depth"]=5, ["max_diffuse_depth"]=2, ["lights_visible_in_camera"]=false, ["enable_motion_blur"]=false, ["enable_dof"]=false, ["two_stage_output"]=false }
PerspectiveCamera("/camera") { ["node_xform"]=Mat4(1,0,0,0, 0,0.978148,-0.207912,0, 0,0.207912,0.978148,0, -0.4,2.3,7.6,1), ["focal"]=40.0, ["film_width_aperture"]=36.0, ["near"]=0.01, ["far"]=1000.0 }
SceneVariables { ["camera"]=PerspectiveCamera("/camera") }
EnvLight("/sky") { ["intensity"]=0.35, ["color"]=Rgb(0.8,0.9,1.0) }
RectLight("/key") { ["node_xform"]=Mat4(1,0,0,0, 0,0.258819,-0.965926,0, 0,0.965926,0.258819,0, 1.5,4.5,2.5,1), ["width"]=2.5, ["height"]=2.5, ["intensity"]=0.06 }
LightSet("/lights") { EnvLight("/sky"), RectLight("/key") }
RenderOutput("/beauty") { ["file_name"]="%s", ["result"]=0, ["channel_format"]=0, ["compression"]=1 }
UsdPreviewSurface("/floor_m") { ["diffuseColor"]=Rgb(0.45,0.45,0.42), ["useSpecularWorkflow"]=1 }
DwaBaseMaterial("/gloss") { ["albedo"]=Rgb(0.8,0.2,0.1), ["roughness"]=0.12 }
DwaBaseMaterial("/metal") { ["metallic"]=1, ["metallic_color"]=Rgb(0.9,0.8,0.5), ["roughness"]=0.18 }
DwaBaseMaterial("/blue") { ["albedo"]=Rgb(0.1,0.3,0.8), ["roughness"]=0.25 }
''' % (samples, exr.replace('\\', '/'))
scene += floor + mesh('/patch', patch_v, patch_f, True, patch_uv) + mesh('/sphere', sphere_v, sphere_f) + mesh('/prism', prism_v, prism_f) + mesh('/star', star_v, star_f, False, star_uv)
scene += 'GeometrySet("/geometry") { RdlMeshGeometry("/floor"),RdlMeshGeometry("/patch"),RdlMeshGeometry("/sphere"),RdlMeshGeometry("/prism"),RdlMeshGeometry("/star") }\n'
scene += ('Layer("/layer") { { RdlMeshGeometry("/floor"), "", UsdPreviewSurface("/floor_m"), LightSet("/lights") },'
          '{ RdlMeshGeometry("/patch"), "", DwaBaseMaterial("/metal"), LightSet("/lights") },'
          '{ RdlMeshGeometry("/sphere"), "", DwaBaseMaterial("/gloss"), LightSet("/lights") },'
          '{ RdlMeshGeometry("/prism"), "", DwaBaseMaterial("/blue"), LightSet("/lights") },'
          '{ RdlMeshGeometry("/star"), "", DwaBaseMaterial("/gloss"), LightSet("/lights") } }\n')
scene += 'SceneVariables { ["layer"]=Layer("/layer") }\n'
open(out, 'w', encoding='utf-8').write(scene)
print('quads', len(patch_f), 'sphere faces', len(sphere_f), 'prism faces', len(prism_f))
