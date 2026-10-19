"""Modo's Principled sheen as DwaBaseMaterial's fuzz: none without sheen; with it, fuzz scaled as fitted against
Modo's renders, white untinted and tinted towards the base colour's hue (no channel past 1), also through a stack."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import moonshine, rdla
from moonray_modo.material_groups import merged


def text(**material):
    return rdla.scene_text({'camera': {'matrix': rdla.IDENTITY, 'focal_mm': 50, 'film_mm': 36},
                            'meshes': [{'name': 'ball', 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'faces': [[0, 1, 2]], 'material': 'm'}],
                            'materials': {'m': dict({'color': [.8, .1, .1], 'shader': 'DwaBaseMaterial'}, **material)}})


class PrincipledSheen(unittest.TestCase):
    def test_no_sheen_no_fuzz(self):
        self.assertNotIn('"fuzz"', text())

    def test_sheen_is_fuzz(self):
        written = text(sheen=1.0)
        self.assertIn('["show_fuzz"] = true', written)
        self.assertIn('["fuzz"] = %g' % moonshine.SHEEN_FUZZ, written)
        self.assertIn('["fuzz_albedo"] = Rgb(1, 1, 1)', written)

    def test_tint_follows_the_base_hue(self):
        attributes = moonshine.sheen({'sheen': 1.0, 'sheen_tint': 1.0, 'color': [.8, .1, .1]}, str, lambda v, kind: v)
        red, green, blue = attributes['fuzz_albedo']
        self.assertEqual(red, 1.0)
        self.assertLess(green, .5)
        self.assertEqual(green, blue)

    def test_a_stack_keeps_the_colour_for_the_tint(self):
        self.assertEqual(merged([{'color': [.8, .1, .1], 'raw_color': [.8, .1, .1], 'sheen': 1.0}])['sheen_color'], [.8, .1, .1])


if __name__ == '__main__':
    unittest.main()
