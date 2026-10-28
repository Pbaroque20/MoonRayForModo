"""n-gons as MoonRay triangulates them (polygons.py, TriMesh::splitNGons): a flat concave one ear-clipped so that its
triangles stay inside it, where a fan covered its notch; a quad, a face that is not flat and one with no area fanned;
and MoonLightIPR's packed mesh made of the ear-clipped triangles."""
import pathlib
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_scene, polygons  # noqa: E402

# An L of six corners, its notch at (1..2, 1..2), begun at a corner a fan from which crosses the notch.
L_SHAPE = [(2.0, 0.0, 0.0), (2.0, 1.0, 0.0), (1.0, 1.0, 0.0), (1.0, 2.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 0.0)]


def inside_l(x, y):
    return 0 <= x <= 2 and 0 <= y <= 2 and not (x > 1 and y > 1)


def triangles(points, flat):
    return [tuple(points[flat[i + k]] for k in range(3)) for i in range(0, len(flat), 3)]


def area(t):
    (ax, ay, _), (bx, by, _), (cx, cy, _) = t
    return abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2


class Polygons(unittest.TestCase):
    def test_a_concave_ngon_is_filled_where_it_is(self):
        clipped = polygons.ear_clip(L_SHAPE)
        self.assertIsNotNone(clipped)
        self.assertEqual(len(clipped), 3 * 4)
        tris = triangles(L_SHAPE, clipped)
        self.assertAlmostEqual(sum(map(area, tris)), 3.0)
        for t in tris:
            centre = (sum(p[0] for p in t) / 3, sum(p[1] for p in t) / 3)
            self.assertTrue(inside_l(*centre), t)
        # A fan from the first corner covers the notch.
        fanned = triangles(L_SHAPE, polygons.fan(6))
        self.assertGreater(sum(map(area, fanned)), 3.0)

    def test_what_moonray_fans(self):
        quad = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        self.assertIsNone(polygons.ear_clip(quad))
        bent = [list(p) for p in L_SHAPE]
        bent[4][2] = 0.5
        self.assertIsNone(polygons.ear_clip(bent))
        self.assertIsNone(polygons.ear_clip([(0, 0, 0)] * 6))
        self.assertEqual(polygons.corners([0, 1, 2, 3], quad), polygons.fan(4))

    def test_moonlightipr_packs_the_ear_clipped_triangles(self):
        mesh = {'name': 'L', 'vertices': [list(p) for p in L_SHAPE], 'faces': [[0, 1, 2, 3, 4, 5]], 'smooth': False}
        moonlightipr_scene._packed.clear()
        key, flags, payload, slots = moonlightipr_scene.mesh_payload(mesh, {'': 0}, {'': 0})
        points, count = struct.unpack_from('<2I', payload)
        self.assertEqual(count, 4)
        start = 8 + 4 * 3 * points
        indices = struct.unpack_from('<%dI' % (3 * count), payload, start)
        self.assertEqual(sorted(indices), sorted(polygons.ear_clip(L_SHAPE)))


if __name__ == '__main__':
    unittest.main()
