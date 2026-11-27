"""Modo's Smooth Positions (render item dispSmooth, on by default): a displaced polygon cage is cut onto Phong
tessellation's surface at a shape factor of a half, as Modo's render cache gave it for a 16-sided cylinder
(tools/probe_cl_smooth_positions.py: 0.99907 of the radius mid-side, 0.98086 flat). The kit hands every engine the cage
split onto that surface (smooth_positions), and MoonRay cuts it as many times less finely."""
import math
import sys
import types
import unittest
from pathlib import Path

for name in ('modo', 'lx', 'lxifc', 'lxu', 'lxu.utils'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_scene, rdla, smooth_positions


def column(segments=16):
    vertices = [[math.sin(2 * math.pi * s / segments), -1.0 + r, math.cos(2 * math.pi * s / segments)] for r in range(3) for s in range(segments)]
    faces = [[r * segments + s, r * segments + (s + 1) % segments, (r + 1) * segments + (s + 1) % segments, (r + 1) * segments + s]
             for r in range(2) for s in range(segments)]
    uvs = [[c % segments / segments, c // segments / 2] for face in faces for c in face]
    return {'name': 'column', 'vertices': vertices, 'faces': faces, 'uvs': uvs, 'material': 'bumpy',
            'face_materials': ['bumpy'] * len(faces)}


def radius(point):
    return math.hypot(point[0], point[2])


class SmoothPositions(unittest.TestCase):
    def test_as_modo_cuts_it(self):
        made = smooth_positions.refine(column(), 8)
        # Mid-side of every side, at any height: Modo's 0.99907; the flat side's 0.98079.
        middles = [radius(p) for p in made['vertices'] if abs(((math.atan2(p[0], p[2]) % (math.pi / 8)) / (math.pi / 8)) - 0.5) < 1e-6]
        self.assertTrue(middles)
        for r in middles:
            self.assertAlmostEqual(r, 0.99907, delta=0.0005)
        # The corners where they were.
        self.assertEqual(made['vertices'][:48], [tuple(v) for v in column()['vertices']])

    def test_watertight(self):
        # Each edge's points made once for both its faces: (16 sides x 2 rows) quads split 8 times.
        made = smooth_positions.refine(column(), 8)
        self.assertEqual(len(made['faces']), 32 * 64)
        self.assertEqual(len(made['vertices']), 16 * 8 * (2 * 8 + 1))
        used = {k for face in made['faces'] for k in face}
        self.assertEqual(len(used), len(made['vertices']))
        edges = {}
        for face in made['faces']:
            for a, b in zip(face, face[1:] + face[:1]):
                edges[(min(a, b), max(a, b))] = edges.get((min(a, b), max(a, b)), 0) + 1
        # An open column: only its top and bottom rims are edges of one face.
        self.assertEqual(sum(1 for count in edges.values() if count == 1), 2 * 16 * 8)

    def test_corners_carried(self):
        made = smooth_positions.refine(column(), 4)
        self.assertEqual(len(made['uvs']), sum(map(len, made['faces'])))
        self.assertEqual(made['face_materials'], ['bumpy'] * len(made['faces']))
        self.assertEqual(made['uvs'][:4], [[0.0, 0.0], [0.25 / 16, 0.0], [0.25 / 16, 0.125], [0.0, 0.125]])

    def test_triangles_and_ngons(self):
        mesh = {'vertices': [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0.5, 1.5, 0], [0, 1, 0]], 'faces': [[0, 1, 2, 3, 4]]}
        made = smooth_positions.refine(mesh, 3)
        self.assertEqual(len(made['faces']), 3 * 9)
        # Flat: every point stays in its plane.
        self.assertTrue(all(abs(p[2]) < 1e-12 for p in made['vertices']))

    def test_splits(self):
        # A degree's turn of the normals each, at most MoonRay's own cut; none for a flat cage.
        self.assertEqual(smooth_positions.splits(column(), 64), 12)
        self.assertEqual(smooth_positions.splits(column(), 4), 4)
        flat = {'vertices': [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], 'faces': [[0, 1, 2, 3]]}
        self.assertEqual(smooth_positions.splits(flat, 64), 1)
        self.assertEqual(smooth_positions.resolution(58, 12), 5)


ADAPTER = [Path(__file__).resolve().parents[1] / 'build/modo-geometry-smooth/MoonRayGeometry.lx',
           Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/bin/MoonRayGeometry.lx']


@unittest.skipUnless(any(p.is_file() for p in ADAPTER), 'no geometry adapter built')
class Native(unittest.TestCase):
    """The adapter's split (MR_smooth_split) makes the same mesh as the Python one, and lifts the Python budget."""
    def setUp(self):
        import ctypes
        from moonray_modo import rows
        self.held = rows.NATIVE
        library = ctypes.CDLL(str(next(p for p in ADAPTER if p.is_file())))
        if not hasattr(library, 'MR_smooth_split'):
            self.skipTest('adapter older than the kit')
        rows.adapter(library)

    def tearDown(self):
        from moonray_modo import rows
        rows.NATIVE = self.held

    def test_same_as_python(self):
        mesh = column()
        mesh['normals'] = [[math.sin(2 * math.pi * (c % 16) / 16), 0.0, math.cos(2 * math.pi * (c % 16) / 16)]
                           for face in mesh['faces'] for c in face]
        mesh['faces'].append([0, 1, 17])                      # a triangle
        mesh['uvs'] += [[0, 0], [1, 0], [1, 1]]
        mesh['normals'] += [[0, 0, 1]] * 3
        mesh['face_materials'].append('bumpy')
        mesh['vertices_close'] = [[x + 0.1, y, z] for x, y, z in mesh['vertices']]
        made = smooth_positions._native_refine(mesh, 6)
        python = smooth_positions._refine(mesh, 6)
        self.assertIsNotNone(made)
        self.assertEqual([list(f) for f in made['faces']], python['faces'])
        for key in ('vertices', 'vertices_close', 'uvs', 'normals'):
            self.assertEqual(len(made[key]), len(python[key]))
            for a, b in zip(made[key], python[key]):
                self.assertTrue(all(abs(x - y) < 1e-5 for x, y in zip(a, b)), key)
        self.assertEqual(made['face_materials'], python['face_materials'])
        vertices = [tuple(v) for v in mesh['vertices']]
        turn = 0.0
        for face, corners in zip(mesh['faces'], smooth_positions.corner_normals(mesh, vertices, mesh['faces'])):
            n = smooth_positions._unit(smooth_positions._face_normal([vertices[k] for k in face]))
            turn = max(turn, max(math.degrees(math.acos(max(-1.0, min(1.0, smooth_positions._dot(n, c))))) for c in corners))
        self.assertAlmostEqual(smooth_positions._native_turn(mesh), turn, places=4)

    def test_large_cage(self):
        # 20,000 quads of a bent sheet split 4 times (320,000 quads): past the Python budget, quick here.
        import time
        vertices = [[i * 0.01, j * 0.01, math.sin(i * 0.3) * 0.05] for j in range(101) for i in range(201)]
        faces = [[j * 201 + i, j * 201 + i + 1, (j + 1) * 201 + i + 1, (j + 1) * 201 + i] for j in range(100) for i in range(200)]
        began = time.perf_counter()
        made = smooth_positions.refine({'vertices': vertices, 'faces': faces}, 4)
        self.assertEqual(len(made['faces']), 20000 * 16)
        self.assertLess(time.perf_counter() - began, 10.0)
        self.assertGreater(smooth_positions.budget(), smooth_positions.TRIANGLES)


def scene(**extra):
    layer = {'identity': 'layer', 'kind': 'constant', 'effect': 'displace', 'value': [.5, .5, .5], 'opacity': 1,
             'blend': 'normal', 'groups': [], 'absolute_groups': []}
    made = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 4, 1], 'focal_mm': 50, 'film_mm': 36},
            'meshes': [column()], 'displacement_min_edge': 0.0001,
            'materials': {'bumpy': {'color': [.5, .5, .5], 'layers': [layer], 'displacement_distance': 0.05}}}
    made.update(extra)
    return made


def resolution(text):
    return int(text.split('["mesh_resolution"] = ')[1].split(',')[0])


class Handed(unittest.TestCase):
    def test_moonray_given_the_smooth_cage(self):
        text = rdla.scene_text(scene())
        flat = rdla.scene_text(scene(displacement_smooth=False))
        # Split 12 times onto the smooth surface, cut 12 times less finely.
        self.assertEqual(resolution(text), smooth_positions.resolution(resolution(flat), 12))
        self.assertGreater(len(text), len(flat))

    def test_moonlightipr_welds_displaced_corners(self):
        # A displaced polygon mesh's corner normals are left out, hard edges too, as MoonRay drops a displaced mesh's
        # normals: one vertex a point, displaced once along its smooth normal, no crack. A subdivision surface keeps its own.
        mesh = column()
        mesh['normals'] = [[math.sin(2 * math.pi * (c % 16) / 16), 0.0, math.cos(2 * math.pi * (c % 16) / 16)]
                           for face in mesh['faces'] for c in face]
        self.assertIsNone(moonlightipr_scene.welded(mesh)['normals'])
        hard = dict(mesh, normals=[list(n) for n in mesh['normals']])
        hard['normals'][0] = [0.0, 1.0, 0.0]
        self.assertIsNone(moonlightipr_scene.welded(hard)['normals'])
        smooth = dict(mesh, subdivision=True)
        self.assertIs(moonlightipr_scene.welded(smooth), smooth)

    def test_moonlightipr_cap_shared(self):
        # Hero heads as before while there are few; past 15, the displaced meshes share 6 M triangles.
        self.assertEqual(moonlightipr_scene.displaced_cap(1), moonlightipr_scene.DISPLACED_TRIANGLES)
        self.assertEqual(moonlightipr_scene.displaced_cap(15), moonlightipr_scene.DISPLACED_TRIANGLES)
        self.assertEqual(moonlightipr_scene.displaced_cap(40), 150000)
        self.assertLessEqual(40 * moonlightipr_scene.displaced_cap(40), moonlightipr_scene.TOTAL_DISPLACED_TRIANGLES)


if __name__ == '__main__':
    unittest.main()
