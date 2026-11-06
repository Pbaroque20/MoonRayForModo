"""Polygons cut by the geometry adapter (native-modo/triangulate.cpp, polygons.triangulate) against polygons.py's own
cutting, a face at a time: the same triangles under MoonRay's rules and under the override's, n-gons convex, concave,
non-planar, degenerate and tiny, quads and triangles kept whole for MoonRay (cut_mesh) and all cut for MoonLightIPR."""
import math
import os
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / 'build/modo-bridge/MoonRayGeometry.lx'
os.environ.setdefault('MOONRAY_MODO_GEOMETRY', str(ADAPTER))
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import polygons, rows  # noqa: E402


def shapes(seed):
    """A mesh of every kind of face: triangles, quads, regular and squashed n-gons, an L, a C, one bent out of its
    plane, one folded on itself, a tiny one, and one with repeated points."""
    chance = random.Random(seed)
    vertices, faces = [], []

    def face(points):
        start = len(vertices)
        vertices.extend([list(map(float, p)) for p in points])
        faces.append(list(range(start, start + len(points))))
    for k in range(6):
        x = k * 3.0
        face([(x, 0, 0), (x + 1, 0, 0), (x, 1, 0)])
        face([(x, 2, 0), (x + 1, 2, 0), (x + 1, 3, 0), (x, 3, 0)])
        n = 5 + k
        face([(x + math.cos(2 * math.pi * i / n), 5 + math.sin(2 * math.pi * i / n) * (.2 + k * .2), chance.uniform(-1e-7, 1e-7)) for i in range(n)])
    face([(0, 10, 0), (3, 10, 0), (3, 11, 0), (1, 11, 0), (1, 13, 0), (0, 13, 0)])                         # an L
    face([(5, 10, 0), (8, 10, 0), (8, 11, 0), (6, 11, 0), (6, 12, 0), (8, 12, 0), (8, 13, 0), (5, 13, 0)])  # a C
    face([(10, 10, 0), (12, 10, .5), (13, 11, 0), (12, 12, -.5), (10, 12, 0)])                            # not flat
    face([(15, 10, 0), (17, 10, 0), (15, 12, 0), (17, 12, 0), (16, 13, 0)])                               # folded
    face([(20, 10, 0), (20 + 1e-5, 10, 0), (20 + 1e-5, 10 + 1e-5, 0), (20 + .5e-5, 10 + 1.5e-5, 0), (20, 10 + 1e-5, 0)])  # tiny
    face([(22, 10, 0), (24, 10, 0), (24, 12, 0), (24, 12, 0), (22, 12, 0), (21, 11, 0)])                  # a point twice
    for i, f in enumerate(list(faces)):
        if i % 2:
            faces[i] = list(reversed(f))                                                                 # either way round
    return vertices, faces


def mesh_of(seed):
    vertices, faces = shapes(seed)
    corners = sum(len(f) for f in faces)
    chance = random.Random(seed + 1)
    return {'vertices': vertices, 'faces': faces, 'uvs': [[chance.random(), chance.random()] for _ in range(corners)],
            'normals': [[0.0, 0.0, 1.0]] * corners, 'face_materials': ['m%d' % (i % 3) for i in range(len(faces))]}


@unittest.skipUnless(ADAPTER.is_file(), 'the geometry adapter is not built (tools/build_modo_bridge.py)')
class NativeTriangulate(unittest.TestCase):
    def setUp(self):
        if rows._native() is None or not hasattr(rows._native(), 'MR_triangulate'):
            self.skipTest('the adapter has no MR_triangulate')
        self.rules = polygons._RULES['clean']

    def tearDown(self):
        polygons.follow(self.rules)

    def by_python(self, mesh):
        held = polygons._cut_natively
        polygons._cut_natively = lambda *a, **k: None
        try:
            return polygons._cut_mesh(mesh, rows.counts)
        finally:
            polygons._cut_natively = held

    def test_cut_for_moonray_as_in_python(self):
        for clean in (True, False):
            polygons.follow(clean)
            for seed in range(3):
                mesh = mesh_of(seed)
                expected = self.by_python(mesh)
                made = polygons._cut_mesh(mesh, rows.counts)
                with self.subTest(clean=clean, seed=seed):
                    self.assertEqual([list(f) for f in made['faces']], [list(f) for f in expected['faces']])
                    self.assertEqual([list(v) for v in made['uvs']], [list(v) for v in expected['uvs']])
                    self.assertEqual([list(v) for v in made['normals']], [list(v) for v in expected['normals']])
                    self.assertEqual(list(made['face_materials']), list(expected['face_materials']))

    def test_cut_into_triangles_as_corners_and_fan_cut(self):
        for clean in (True, False):
            polygons.follow(clean)
            vertices, faces = shapes(7)
            places, from_face, sizes, corners = polygons.triangulate(vertices, faces, False)
            expected, start = [], 0
            for face in faces:
                cut = polygons.corners(face, vertices) if len(face) > 4 else polygons.fan(len(face))
                expected += [start + k for k in cut]
                start += len(face)
            with self.subTest(clean=clean):
                self.assertEqual(list(places), expected)
                self.assertEqual(set(sizes), {3})
                self.assertEqual(len(from_face) * 3, len(places))


if __name__ == '__main__':
    unittest.main()


@unittest.skipUnless(ADAPTER.is_file(), 'the geometry adapter is not built (tools/build_modo_bridge.py)')
class PackedTheSame(unittest.TestCase):
    """MoonLightIPR's packing of a mesh (moonlightipr_scene.mesh_payload): the same bytes cut by the adapter as cut here."""

    def packed(self, mesh, native):
        from moonray_modo import moonlightipr_scene
        moonlightipr_scene._packed.clear()
        held = polygons.triangulate
        if not native:
            polygons.triangulate = lambda *a, **k: None
        try:
            return moonlightipr_scene.mesh_payload(dict(mesh), {'': 0, 'm0': 1, 'm1': 2, 'm2': 3}, {'': 0})
        finally:
            polygons.triangulate = held

    def test_quads_and_mixed_meshes(self):
        quads = {'name': 'Quads', 'vertices': [[x, y, 0.0] for y in range(4) for x in range(4)],
                 'faces': [[y * 4 + x, y * 4 + x + 1, (y + 1) * 4 + x + 1, (y + 1) * 4 + x] for y in range(3) for x in range(3)]}
        quads['uvs'] = [[c / 16.0, .5] for f in quads['faces'] for c in f]
        quads['face_materials'] = ['m%d' % (i % 3) for i in range(len(quads['faces']))]
        mixed = mesh_of(4)
        mixed['name'] = 'Mixed'
        plain = dict(mixed)
        plain.pop('normals')
        for name, mesh in (('quads', quads), ('mixed', mixed), ('mixed without normals', plain)):
            with self.subTest(mesh=name):
                self.assertEqual(self.packed(mesh, True), self.packed(mesh, False))


@unittest.skipUnless(ADAPTER.is_file(), 'the geometry adapter is not built (tools/build_modo_bridge.py)')
class SimplifiedTheSame(unittest.TestCase):
    """The realtime simplifier's cutting of a mesh before it is made lighter (simplify.polygon_mesh), by the adapter."""

    def simplified(self, mesh, native):
        from moonray_modo import simplify
        simplify._MESHES.clear()
        held = polygons.triangulate
        if not native:
            polygons.triangulate = lambda *a, **k: None
        try:
            return simplify.polygon_mesh(dict(mesh), 40, .01)
        finally:
            polygons.triangulate = held

    def test_mixed_mesh(self):
        mesh = mesh_of(5)
        mesh.pop('normals')
        native, python = self.simplified(mesh, True), self.simplified(mesh, False)
        if native is None and python is None:
            self.skipTest('the simplifier is not in this adapter')
        for key in ('vertices', 'faces', 'uvs', 'face_materials'):
            with self.subTest(key=key):
                self.assertEqual([list(v) if not isinstance(v, str) else v for v in native[key]],
                                 [list(v) if not isinstance(v, str) else v for v in python[key]])
