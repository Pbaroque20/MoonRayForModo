"""A mesh's corner normals repaired before they are written (rows.repaired_normals, rdla's normal_list): no normal of no
length and none not a number reaches MoonRay or XPU2. A tester's Enterprise (3.7 million polygons) had 24 corners of
no length from smoothing polygons of no area; XPU2 refused it ("invalid normal") or failed on the graphics card (CUDA
error 719) and the scene went to MoonRay XPU."""
import math
import pathlib
import sys
import unittest
from array import array

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import rows  # noqa: E402

UP = [0.0, 0.0, 1.0]
QUAD = [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]


def normals_of(result):
    return [list(n) for n in result]


class Repaired(unittest.TestCase):
    def test_good_normals_are_given_back_as_they_are(self):
        values = [UP] * 4
        self.assertIs(rows.repaired_normals(values, [[0, 1, 2, 3]], QUAD), values)

    def test_a_corner_of_no_length_takes_its_polygons_good_corner(self):
        values = [UP, [0.0, 0.0, 0.0], UP, UP]
        self.assertEqual(normals_of(rows.repaired_normals(values, [[0, 1, 2, 3]], QUAD)), [UP] * 4)

    def test_a_polygon_all_of_no_length_takes_its_own_normal(self):
        vertices = QUAD + [[0, 0, 0], [0, 0, 1], [0, 1, 1]]
        values = [UP] * 4 + [[0.0, 0.0, 0.0]] * 3
        out = normals_of(rows.repaired_normals(values, [[0, 1, 2, 3], [4, 5, 6]], vertices))
        self.assertEqual(out[:4], [UP] * 4)
        for n in out[4:]:
            self.assertAlmostEqual(abs(n[0]), 1.0, places=6)   # the triangle in the x = 0 plane
            self.assertAlmostEqual(math.sqrt(sum(v * v for v in n)), 1.0, places=6)

    def test_a_polygon_of_no_area_gets_a_unit_normal(self):
        vertices = [[0, 0, 0], [0, 0, 0], [0, 0, 0]]
        out = normals_of(rows.repaired_normals([[0.0, 0.0, 0.0]] * 3, [[0, 1, 2]], vertices))
        for n in out:
            self.assertAlmostEqual(math.sqrt(sum(v * v for v in n)), 1.0, places=6)

    def test_a_normal_not_a_number_is_repaired(self):
        values = [UP, [float('nan'), 0.0, 0.0], UP, UP]
        out = normals_of(rows.repaired_normals(values, [[0, 1, 2, 3]], QUAD))
        self.assertEqual(out[1], UP)

    def test_rows_as_the_adapter_makes_them(self):
        flat = array('f', UP * 3 + [0.0, 0.0, 0.0])
        made = rows.Rows(flat, 3, 'test')
        out = rows.repaired_normals(made, [[0, 1, 2, 3]], QUAD)
        self.assertIsInstance(out, rows.Rows)
        self.assertEqual(normals_of(out)[3], UP)
        self.assertEqual(list(flat[9:12]), [0.0, 0.0, 0.0])   # the given ones untouched


if __name__ == '__main__':
    unittest.main()
