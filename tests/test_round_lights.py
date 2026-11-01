import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))

from moonray_modo import entities


def scaled(x, y, z, at=(1, 2, 3)):
    return [x, 0, 0, 0, 0, y, 0, 0, 0, 0, z, 0, at[0], at[1], at[2], 1]


def length(matrix, row):
    return math.sqrt(sum(v * v for v in matrix[row * 4:row * 4 + 3]))


class RoundLights(unittest.TestCase):
    def test_a_disk_keeps_its_area_and_its_place(self):
        made = entities.round_light('DiskLight', scaled(2, 8, 3))
        for row in range(3):
            self.assertAlmostEqual(length(made, row), 4.0)
        self.assertEqual(made[12:16], [1.0, 2.0, 3.0, 1.0])

    def test_a_sphere_takes_the_mean_of_all_three(self):
        self.assertAlmostEqual(length(entities.round_light('SphereLight', scaled(1, 8, 27)), 0), 6.0)

    def test_it_still_faces_the_way_it_faced_under_a_slanted_parent(self):
        slanted = [2, 1, 0, 0, 0, 3, 0, 0, 0, 0, 5, 0, 0, 0, 0, 1]
        made = entities.round_light('DiskLight', slanted)
        self.assertEqual([round(v / length(made, 2), 6) for v in made[8:11]], [0, 0, 1])
        self.assertAlmostEqual(sum(a * b for a, b in zip(made[0:3], made[4:7])), 0.0)

    def test_an_even_scale_is_left_exactly_as_it_is(self):
        even = scaled(2, 2, 2)
        self.assertIs(entities.round_light('DiskLight', even), even)

    def test_a_mirrored_light_keeps_its_mirror(self):
        made = entities.round_light('DiskLight', scaled(-2, 8, 3))
        self.assertLess(made[0], 0)

    def test_a_rect_light_takes_an_uneven_scale_itself(self):
        uneven = scaled(2, 8, 3)
        self.assertIs(entities.round_light('RectLight', uneven), uneven)


if __name__ == '__main__':
    unittest.main()
