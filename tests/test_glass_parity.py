"""Modo's glass in MoonRay: its Transmission Color through a solid (Modo tints once, MoonRay at each surface, so a
Modo material's colour reaches MoonRay as its square root, plain or from the Shader Tree through a gamma map; a thin
surface and MoonRay's own materials keep it as it is), and its refraction roughness through the curve fitted to Modo's
renders, plain or through a ramp."""
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


class RefractionRoughness(unittest.TestCase):
    def test_the_fitted_points(self):
        for modo, moonray in ((0, 0), (.1, .4), (.3, .55), (.6, .6), (.9, .7)):
            self.assertAlmostEqual(moonshine.refraction_through({'standard_material': True}, modo), moonray)

    def test_between_points_straight(self):
        self.assertAlmostEqual(moonshine.refraction_through({'standard_material': True}, .2), .475)

    def test_moonray_materials_keep_theirs(self):
        self.assertEqual(moonshine.refraction_through({'standard_material': False}, .3), .3)


if __name__ == '__main__':
    unittest.main()
