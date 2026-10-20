"""Modo's Transmission Color through a glass solid: Modo tints once, MoonRay at each surface, so a Modo material's
colour reaches MoonRay as its square root (plain or from the Shader Tree, through a gamma map); a thin surface and
MoonRay's own materials keep it as it is."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import moonshine


class GlassTint(unittest.TestCase):
    def test_a_solid_is_given_the_square_root(self):
        tinted = moonshine.passed_once({'standard_material': True, 'transmission_color': [.25, .81, 1.0]})
        self.assertEqual([round(c, 6) for c in tinted], [.5, .9, 1.0])

    def test_a_thin_surface_keeps_the_colour(self):
        self.assertEqual(moonshine.passed_once({'standard_material': True, 'thin_geometry': True, 'transmission_color': [.25, .5, 1]}), [.25, .5, 1])

    def test_moonray_materials_keep_the_colour(self):
        self.assertEqual(moonshine.passed_once({'standard_material': False, 'transmission_color': [.25, .5, 1]}), [.25, .5, 1])

    def test_the_gamma_map_takes_the_square_root(self):
        self.assertEqual(moonshine.TINT_GAMMA, 2.0)


if __name__ == '__main__':
    unittest.main()
