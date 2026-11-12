"""Modo's Process texture: read as pattern 401 (modo_patterns.h mp_modo_process), its Hue, Saturation, Value and Hue Shift
as Modo renders them; Bias and Gain away from 0.5 named as not followed. No Modo."""
import colorsys
import math
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))

from moonray_modo import procedurals  # noqa: E402


def channel_of(values):
    return lambda layer, name, default=None: values.get(name, default)


def process(rgb, hue=0.0, sat=0.0, val=0.0, shift=0.0):
    """The formula mp_modo_process carries, in Python."""
    h, s, v = colorsys.rgb_to_hsv(*rgb)
    return colorsys.hsv_to_rgb((h * (1 + hue) + shift / (2 * math.pi)) % 1, min(1, max(0, s * (1 + sat))), max(0, v * (1 + val)))


class ModoProcess(unittest.TestCase):
    def test_read_as_pattern_401(self):
        record, moved = procedurals.modo_process(None, channel_of({'hue': .25, 'sat': -.5, 'val': .5, 'hueShift': .25, 'bias': .5, 'gain': .5}))
        self.assertEqual(record['pattern'], 401)
        self.assertTrue(record['process'])
        self.assertEqual(record['settings'][:4], [.25, -.5, .5, .25])
        self.assertFalse(moved)

    def test_bias_and_gain_named(self):
        self.assertTrue(procedurals.modo_process(None, channel_of({'bias': .3}))[1])
        self.assertTrue(procedurals.modo_process(None, channel_of({'gain': .7}))[1])

    def test_the_formula_matches_modos_renders(self):
        # From probe_gui_process_layer.py (test-results/process-layer/measured.json).
        measured = {((.8, .3, .1), 'hue', .25): (.7998, .3501, .1000), ((.2, .5, .9), 'hue', .25): (.5249, .2000, .8999),
                    ((.8, .3, .1), 'sat', -.5): (.7998, .5498, .4500), ((.2, .5, .9), 'val', .5): (.3000, .7500, 1.3496),
                    ((.8, .3, .1), 'shift', 90.0): (.1000, .7998, .2605), ((.2, .5, .9), 'shift', .25): (.2000, .3330, .8999)}
        for (rgb, what, amount), want in measured.items():
            got = process(rgb, **{what: amount})
            self.assertLess(max(abs(a - b) for a, b in zip(got, want)), 1e-3, (rgb, what, amount, got, want))

    def test_the_shared_header_has_it(self):
        source = (ROOT / 'native-port/maps/ModoProcedural/modo_patterns.h').read_text(encoding='utf-8')
        self.assertIn('if (pattern == 401) return mp_modo_process(r, g, b, s);', source)


if __name__ == '__main__':
    unittest.main()
