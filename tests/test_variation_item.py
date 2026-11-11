"""Modo's Variation Texture by Item: each mesh's points carry one number of its own, the same each time, when a layer
reads it; and no number is added when no layer asks."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import occlusion, procedurals  # noqa: E402


def scene(read):
    layer = {'kind': 'gradient', 'vmap': procedurals.VARIATION_MAP} if read else {'kind': 'constant'}
    return {'materials': {'m': {'layers': [layer]}},
            'meshes': [{'name': n, 'identity': n + '|x', 'vertices': [(0, 0, 0), (1, 0, 0), (0, 1, 0)], 'faces': [(0, 1, 2)]}
                       for n in ('CubeA', 'CubeB')]}


class VariationItem(unittest.TestCase):
    def test_numbers(self):
        first, second = scene(True), scene(True)
        occlusion.variation(first, [])
        occlusion.variation(second, [])
        numbers = [m['point_attributes'][procedurals.VARIATION_MAP]['values'] for m in first['meshes']]
        self.assertEqual(len(numbers[0]), 3)
        self.assertEqual(len({v[0] for v in numbers[0]}), 1)
        self.assertNotEqual(numbers[0][0][0], numbers[1][0][0])
        self.assertTrue(all(0.0 <= n[0][0] <= 1.0 for n in numbers))
        self.assertEqual(numbers, [m['point_attributes'][procedurals.VARIATION_MAP]['values'] for m in second['meshes']])

    def test_not_asked(self):
        held = scene(False)
        occlusion.variation(held, [])
        self.assertTrue(all('point_attributes' not in m for m in held['meshes']))

    def test_copies_named(self):
        held = scene(True)
        held['meshes'][0]['instances'] = [[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]] * 2
        warnings = []
        occlusion.variation(held, warnings)
        self.assertEqual(len(warnings), 1)


if __name__ == '__main__':
    unittest.main()
