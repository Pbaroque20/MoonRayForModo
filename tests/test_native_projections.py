"""Locator projections by the geometry adapter (native-modo/projections.cpp, coordinates.mesh_corners) against
coordinates.py's own: planar, cubic, cylindrical and spherical, along each axis, in world and object space, moved by
a UV matrix, rotation and scale; faces wrapped across the seam, at the poles, tiny and large. The same numbers, as
32-bit floats; a face that cannot be cubic is still refused as coordinates.py refuses it."""
import math
import os
import random
import sys
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / 'build/modo-bridge/MoonRayGeometry.lx'
os.environ.setdefault('MOONRAY_MODO_GEOMETRY', str(ADAPTER))
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import coordinates, rows  # noqa: E402


def sphere(seed):
    """A ball of quads and triangles around the origin (faces across the seam and at the poles), with odd n-gons and
    a face far out."""
    chance = random.Random(seed)
    vertices, faces = [], []
    rings, segments = 9, 13
    for r in range(rings + 1):
        for s in range(segments):
            t, p = math.pi * r / rings, 2 * math.pi * s / segments
            vertices.append([math.sin(t) * math.cos(p) + chance.uniform(-.01, .01), math.cos(t), math.sin(t) * math.sin(p)])
    for r in range(rings):
        for s in range(segments):
            a, b = r * segments + s, r * segments + (s + 1) % segments
            c, d = b + segments, a + segments
            faces.append([a, b, c, d] if (r + s) % 3 else [a, b, c])
    start = len(vertices)
    vertices += [[40.0 + math.cos(k), 3.0, math.sin(k)] for k in range(7)]
    faces.append(list(range(start, start + 7)))
    faces.append([])
    return vertices, faces


LOCATOR = [1.5, .2, 0, 0, -.1, 2.0, .3, 0, 0, .25, .8, 0, .3, -.2, .1, 1]
WORLD = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 2.0, -1.0, .5, 1]


@unittest.skipUnless(ADAPTER.is_file(), 'the geometry adapter is not built (tools/build_modo_bridge.py)')
class NativeProjections(unittest.TestCase):
    def setUp(self):
        if rows._native() is None or not hasattr(rows._native(), 'MR_project'):
            self.skipTest('the adapter has no MR_project')

    def by_python(self, *given):
        held = coordinates._project_natively
        coordinates._project_natively = lambda *a: None
        try:
            return coordinates.mesh_corners(*given)
        finally:
            coordinates._project_natively = held

    def test_every_projection_axis_and_space(self):
        vertices, faces = sphere(3)
        for projection in coordinates.PROJECTIONS:
            for axis in ('x', 'y', 'z'):
                for object_space in (False, True):
                    for moved in (False, True):
                        layer = {'projection': projection, 'locator_matrix': LOCATOR, 'axis': axis, 'object_space': object_space}
                        if moved:
                            layer.update(uv_matrix=[1.2, .1, .3, -.2, .9, .05], rotation=.7, scale=[2.0, .5])
                        made = coordinates.mesh_corners(layer, vertices, faces, [], WORLD)
                        expected = self.by_python(layer, vertices, faces, [], WORLD)
                        with self.subTest(projection=projection, axis=axis, object_space=object_space, moved=moved):
                            self.assertIsInstance(made, rows.Rows)
                            self.assertEqual(list(made.data), list(array('f', (v for p in expected for v in p))))

    def test_faces_and_points_as_the_mesh_reader_hands_them_over(self):
        vertices, faces = sphere(4)
        faces = [f for f in faces if f]
        flat = rows.Rows(array('f', (v for p in vertices for v in p)), 3, 'v')
        whole = rows.Faces(array('i', (v for f in faces for v in f)), array('i', map(len, faces)), 'f')
        layer = {'projection': 'spherical', 'locator_matrix': LOCATOR, 'axis': 'y'}
        made = coordinates.mesh_corners(layer, flat, whole, [], WORLD)
        expected = self.by_python(layer, [list(p) for p in flat], faces, [], WORLD)
        self.assertEqual(list(made.data), list(array('f', (v for p in expected for v in p))))

    def test_a_face_that_cannot_be_cubic_is_refused_as_before(self):
        layer = {'projection': 'cubic', 'locator_matrix': LOCATOR}
        with self.assertRaisesRegex(ValueError, 'degenerate'):
            coordinates.mesh_corners(layer, [[0, 0, 0], [1, 0, 0], [2, 0, 0]], [[0, 1, 2]], [], WORLD)
        with self.assertRaisesRegex(ValueError, 'requires a polygon'):
            coordinates.mesh_corners(layer, [[0, 0, 0], [1, 0, 0]], [[0, 1]], [], WORLD)


if __name__ == '__main__':
    unittest.main()
