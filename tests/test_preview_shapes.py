"""The graph editor preview's other shapes (preview_shapes): water, subsurface and velvet scenes, each with meshes whose
UVs follow their corners, a camera and lights, at the preview's Scale; tools/check_preview_shapes.py renders them."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import preview_shapes  # noqa: E402


class Shapes(unittest.TestCase):
    def test_each_shape_is_a_whole_scene(self):
        self.assertEqual([key for key, _, _ in preview_shapes.SHAPES], ['widget', 'water', 'subsurface', 'velvet'])
        self.assertIsNone(preview_shapes.made('widget', 1.0))
        for key in ('water', 'subsurface', 'velvet'):
            made = preview_shapes.made(key, 1.0)
            self.assertTrue(made['lights'] and made['camera']['matrix'])
            for mesh in made['meshes']:
                corners = sum(len(face) for face in mesh['faces'])
                self.assertEqual(len(mesh['uvs']), corners, (key, mesh['name']))
                self.assertTrue(all(0 <= i < len(mesh['vertices']) for face in mesh['faces'] for i in face))
                self.assertTrue(all(0 <= c <= 1 for uv in mesh['uvs'] for c in uv))

    def test_the_scale_makes_everything_larger_together(self):
        small, large = preview_shapes.made('water', 1.0), preview_shapes.made('water', 3.0)
        self.assertEqual(large['meshes'][0]['vertices'][5], [v * 3 for v in small['meshes'][0]['vertices'][5]])
        self.assertEqual(large['camera']['matrix'][12:15], [v * 3 for v in small['camera']['matrix'][12:15]])

    def test_the_water_meets_the_sky_without_a_band(self):
        sky = preview_shapes.made('water', 1.0)['environments'][0]
        self.assertEqual(sky['ground'], sky['sky'])


if __name__ == '__main__':
    unittest.main()
