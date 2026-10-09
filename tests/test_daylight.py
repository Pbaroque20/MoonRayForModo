"""Modo's physically based daylight, as read from the table of Modo's own renders."""
import math
import sys
import types
import unittest
from pathlib import Path

for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import daylight


def sun_at(elevation):
    return [0.0, math.sin(math.radians(elevation)), math.cos(math.radians(elevation))]


class Daylight(unittest.TestCase):
    def test_zenith_is_what_modo_rendered(self):
        # Modo's own zenith for a sun 30 degrees up and haze 2, unclamped.
        got = daylight.color([0, 1, 0], {'sun_direction': sun_at(30), 'haze': 2.0})
        for ours, theirs in zip(got, (1.643, 3.469, 7.469)):
            self.assertAlmostEqual(ours / theirs, 1.0, delta=.03)

    def test_clamp_divides_and_gamma_shapes(self):
        sky = {'sun_direction': sun_at(30), 'haze': 2.0}
        plain = daylight.color([0, 1, 0], sky)
        clamped = daylight.color([0, 1, 0], dict(sky, normalize=True))
        shaped = daylight.color([0, 1, 0], dict(sky, normalize=True, sky_gamma=2.0))
        self.assertAlmostEqual(plain[2] / clamped[2], 29.7, delta=.5)
        self.assertAlmostEqual(shaped[2], math.sqrt(clamped[2]), places=5)
        # Unclamped, the gamma does nothing.
        self.assertEqual(plain, daylight.color([0, 1, 0], dict(sky, sky_gamma=2.0)))

    def test_ground_and_the_band_below_the_horizon(self):
        sky = {'sun_direction': sun_at(30), 'haze': 2.0, 'normalize': True, 'ground_albedo': [.2, .3, .4]}
        self.assertEqual(daylight.color([0, -1, 0], sky), [.2, .3, .4])
        horizon = daylight.color([0, 0, -1], sky)
        below = daylight.color([0, -math.sin(.25), -math.cos(.25)], sky)
        for ground, edge, between in zip(sky['ground_albedo'], horizon, below):
            self.assertAlmostEqual(between, ground + .5 * (edge - ground), places=5)

    def test_sun_blends_between_sun_heights(self):
        low, middle, high = (daylight.color([0, 1, 0], {'sun_direction': sun_at(e), 'haze': 2.0}) for e in (30, 37, 45))
        for a, b, c in zip(low, middle, high):
            self.assertTrue(min(a, c) <= b <= max(a, c))

    def test_physical_sun(self):
        tint, strength = daylight.sun_light(46.39, 2.0, True, 2.2, 'clamp', 3.0)
        self.assertEqual(strength, 1.0)
        self.assertEqual(max(tint), 1.0)
        self.assertAlmostEqual(tint[2], .9, delta=.01)
        self.assertEqual(daylight.sun_light(46.39, 2.0, True, 2.2, 'replace', 6.0)[1], 6.0)
        self.assertAlmostEqual(daylight.sun_light(46.39, 2.0, True, 1.0, 'none', 3.0)[1], 219.8, delta=1.0)
        # Lower and hazier is dimmer and redder.
        high, low = daylight.sun_measure(60, 2.0, False), daylight.sun_measure(10, 6.0, False)
        self.assertTrue(low[0] < high[0] and low[2] / low[0] < high[2] / high[0])
        self.assertEqual(daylight.sun_light(-5, 2.0)[1], 0.0)


if __name__ == '__main__':
    unittest.main()
