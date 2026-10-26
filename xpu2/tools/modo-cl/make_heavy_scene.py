"""make_heavy_scene.py <folder> [--grid N] [--torus N] [--instances K] [--mirror]: a synthetic heavy scene written by the
kit's own exporter as the preview hands it over (preview.rdla + preview.rdlb, no textures): a ground of N x N quads
and a torus of N x N/4 quads instanced K times by an RdlInstancerGeometry (every other instance mirrored with
--mirror), like his Lamborghini's tyre. For measuring XPU2's memory per triangle and its instancing against MoonRay."""
import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, r'C:\Users\Raphael Tobar\MoonRayForModo\kit\MoonRayForModo\python')
from moonray_modo import rdla, rdlb  # noqa: E402

p = argparse.ArgumentParser()
p.add_argument('folder', type=Path)
p.add_argument('--grid', type=int, default=1000)
p.add_argument('--torus', type=int, default=400)
p.add_argument('--instances', type=int, default=4)
p.add_argument('--mirror', action='store_true')
p.add_argument('--meshes', action='store_true', help='each tyre a mesh of its own under its transform, no instancer')
p.add_argument('--displace', type=float, default=0.0, help='the tyre material displaced by a constant height times this distance')
p.add_argument('--width', type=int, default=640)
p.add_argument('--height', type=int, default=360)
a = p.parse_args()
a.folder = a.folder.resolve()


def grid(n, size):
    vertices = [[size * (i / n - 0.5), 0.0, size * (j / n - 0.5)] for j in range(n + 1) for i in range(n + 1)]
    faces = [[j * (n + 1) + i, (j + 1) * (n + 1) + i, (j + 1) * (n + 1) + i + 1, j * (n + 1) + i + 1] for j in range(n) for i in range(n)]
    uvs = [[i / n, j / n] for j in range(n + 1) for i in range(n + 1)]
    return vertices, faces, uvs


def torus(n, m, big=0.35, small=0.12):
    vertices, uvs = [], []
    for j in range(m):
        b = 2 * math.pi * j / m
        for i in range(n):
            t = 2 * math.pi * i / n
            r = big + small * math.cos(b)
            vertices.append([r * math.cos(t), small * math.sin(b), r * math.sin(t)])
            uvs.append([i / n, j / m])
    faces = [[j * n + i, j * n + (i + 1) % n, ((j + 1) % m) * n + (i + 1) % n, ((j + 1) % m) * n + i] for j in range(m) for i in range(n)]
    return vertices, faces, uvs


def placed(x, y, z, mirror=False, turn=0.0):
    c, s = math.cos(turn), math.sin(turn)
    sx = -1.0 if mirror else 1.0
    # Row vectors (MoonRay's): the rows are the axes, the last the translation. Stood up on its side, like a wheel.
    return [sx * c, sx * s, 0, 0,  -s, c, 0, 0,  0, 0, 1, 0,  x, y, z, 1]


gv, gf, gu = grid(a.grid, 8.0)
tv, tf, tu = torus(a.torus, max(8, a.torus // 4))
# UVs by face corner, as the kit has them from Modo.
gu = [gu[v] for f in gf for v in f]
tu = [tu[v] for f in tf for v in f]
wheels = [placed(-1.2 + 2.4 * (k % 2), 0.47, -1.5 + 3.0 * (k // 2) / max(1, (a.instances - 1) // 2), a.mirror and k % 2 == 1, math.pi / 2)
          for k in range(a.instances)]
def look(eye, at):
    """A camera at eye looking at at, upright: rows its x, y and z axes (it looks down its -z), then its place."""
    z = [e - t for e, t in zip(eye, at)]
    n = math.sqrt(sum(c * c for c in z))
    z = [c / n for c in z]
    x = [z[2], 0.0, -z[0]]
    n = math.sqrt(sum(c * c for c in x))
    x = [c / n for c in x]
    y = [z[1] * x[2] - z[2] * x[1], z[2] * x[0] - z[0] * x[2], z[0] * x[1] - z[1] * x[0]]
    return x + [0] + y + [0] + z + [0] + list(eye) + [1]


scene = {
    'camera': {'matrix': look([3.4, 2.0, 4.6], [0.0, 0.3, 0.0]), 'focal_mm': 35, 'film_mm': 36},
    'meshes': [
        {'name': 'ground', 'vertices': gv, 'faces': gf, 'uvs': gu, 'material': 'ground'},
    ] + ([{'name': 'tyre%d' % k, 'vertices': tv, 'faces': tf, 'uvs': tu, 'material': 'rubber', 'matrix': m, 'smooth_normal': True} for k, m in enumerate(wheels)]
         if a.meshes else [{'name': 'tyre', 'vertices': tv, 'faces': tf, 'uvs': tu, 'material': 'rubber', 'instances': wheels, 'smooth_normal': True}]),
    'materials': {'ground': {'color': [0.55, 0.55, 0.5], 'roughness': 0.6},
                  'rubber': dict({'color': [0.08, 0.08, 0.09], 'roughness': 0.35},
                                 **({'displacement_distance': a.displace, 'layers': [{'identity': 'bumps', 'kind': 'constant', 'effect': 'displace', 'value': [1, 1, 1],
                                                                                  'opacity': 1, 'blend': 'normal', 'groups': [], 'absolute_groups': []}]}
                                    if a.displace else {}))},
}
a.folder.mkdir(parents=True, exist_ok=True)
with rdlb.collecting() as sink:
    text = rdla.scene_text(scene, a.width, a.height, 2, 0.6, str(a.folder / 'preview.exr'))
(a.folder / 'preview.rdla').write_text(text, encoding='utf-8')
sink.write(a.folder / 'preview.rdlb')
tris = 2 * a.grid * a.grid + 2 * len(tf) * a.instances
print('%s: ground %d triangles, tyre %d triangles x %d instances (%s), %.1f M triangles placed' % (
    a.folder, 2 * a.grid * a.grid, 2 * len(tf), a.instances, 'mirrored' if a.mirror else 'not mirrored', tris / 1e6))
