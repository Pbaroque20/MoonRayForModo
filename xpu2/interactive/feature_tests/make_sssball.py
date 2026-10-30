"""Write a small textureless random-walk subsurface test scene (deterministic in vectorized mode)."""
import math, sys
from pathlib import Path
out = Path(sys.argv[1])
t = (1 + 5 ** 0.5) / 2
V = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0), (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
     (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
F = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11), (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
     (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9), (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]
V = [tuple(c / math.sqrt(sum(x * x for x in v)) for c in v) for v in V]
for _ in range(4):
    cache, nf = {}, []
    def mid(a, b):
        k = (min(a, b), max(a, b))
        if k not in cache:
            m = [(V[a][i] + V[b][i]) / 2 for i in range(3)]
            n = math.sqrt(sum(x * x for x in m)); V.append(tuple(x / n for x in m)); cache[k] = len(V) - 1
        return cache[k]
    for a, b, c in F:
        ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
        nf += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
    F = nf
def mesh(name, verts, faces):
    vl = ', '.join('Vec3(%.6f, %.6f, %.6f)' % v for v in verts)
    idx = ', '.join(str(i) for f in faces for i in f)
    return ('RdlMeshGeometry("%s") {\n  ["vertex_list"] = {%s},\n  ["vertices_by_index"] = {%s},\n'
            '  ["face_vertex_count"] = {%s},\n  ["is_subd"] = false,\n}\n' % (name, vl, idx, ', '.join(str(len(f)) for f in faces)))
ball = [(x, y + 1.0, z) for x, y, z in V]
floor = [(-6, 0, -6), (6, 0, -6), (6, 0, 6), (-6, 0, 6)]
wall = [(-6, 0, -2.5), (6, 0, -2.5), (6, 6, -2.5), (-6, 6, -2.5)]
s = '''SceneVariables {
  ["image_width"] = 480, ["image_height"] = 360, ["pixel_samples"] = 4, ["sampling_mode"] = 0,
  ["max_depth"] = 4,
}
PerspectiveCamera("/cam") { ["node_xform"] = Mat4(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,1.3,5.5,1), ["focal"] = 30 }
DwaBaseMaterial("/mtl/skin") {
  ["albedo"] = Rgb(0.8, 0.45, 0.35), ["roughness"] = 0.45, ["scattering_radius"] = 0.25,
  ["scattering_color"] = Rgb(0.9, 0.55, 0.45), ["bssrdf"] = 2,
}
DwaBaseMaterial("/mtl/floor") { ["albedo"] = Rgb(0.6, 0.6, 0.6), ["roughness"] = 0.8 }
DwaBaseMaterial("/mtl/wall") { ["albedo"] = Rgb(0.3, 0.5, 0.7), ["roughness"] = 0.6 }
RectLight("/light/key") {
  ["node_xform"] = Mat4(1,0,0,0, 0,0,-1,0, 0,1,0,0, 1.5,4,1.5,1),
  ["color"] = Rgb(1, 0.95, 0.9), ["intensity"] = 0.04, ["width"] = 1.5, ["height"] = 1.5,
}
RectLight("/light/rim") {
  ["node_xform"] = Mat4(0,0,1,0, 0,1,0,0, -1,0,0,0, -3,1.5,-1,1),
  ["color"] = Rgb(0.6, 0.7, 1), ["intensity"] = 0.02, ["width"] = 1, ["height"] = 2,
}
EnvLight("/light/env") { ["color"] = Rgb(0.15, 0.17, 0.2) }
LightSet("/lightset") { RectLight("/light/key"), RectLight("/light/rim"), EnvLight("/light/env") }
'''
s += mesh('/geo/ball', ball, F) + mesh('/geo/floor', floor, [(0, 3, 2, 1)]) + mesh('/geo/wall', wall, [(0, 1, 2, 3)])
s += '''GeometrySet("/geoset") { RdlMeshGeometry("/geo/ball"), RdlMeshGeometry("/geo/floor"), RdlMeshGeometry("/geo/wall") }
Layer("/layer") {
  {RdlMeshGeometry("/geo/ball"), "", DwaBaseMaterial("/mtl/skin"), LightSet("/lightset"), undef(), undef(), undef(), undef()},
  {RdlMeshGeometry("/geo/floor"), "", DwaBaseMaterial("/mtl/floor"), LightSet("/lightset"), undef(), undef(), undef(), undef()},
  {RdlMeshGeometry("/geo/wall"), "", DwaBaseMaterial("/mtl/wall"), LightSet("/lightset"), undef(), undef(), undef(), undef()},
}
'''
out.write_text(s)
print(len(V), 'verts', len(F), 'faces')
