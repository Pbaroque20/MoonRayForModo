"""The geometry adapter's procedural bake (native-modo/procedural_bake.cpp, MR_procedural_bake) gives what
procedurals.sample gives, pattern by pattern, each kind and each Grid and Dots shape, with the same random numbers
(BLAKE2b of the whole numbers, as _chance draws them). Needs the adapter built (tools/build_modo_bridge.py)."""
import array
import ctypes
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import procedurals  # noqa: E402


def adapter():
    for build in sorted((ROOT / 'build').glob('modo-geometry*/MoonRayGeometry.lx'), key=lambda p: -p.stat().st_mtime):
        try:
            held = ctypes.CDLL(str(build))
        except OSError:
            continue
        if hasattr(held, 'MR_procedural_bake'):
            return held
    return None


BASE = {'bias': .5, 'gain': .5, 'color1': [.9, .2, .1], 'color2': [.1, .3, .8], 'alpha1': 1.0, 'alpha2': .25}
CASES = [dict(BASE, kind='grid', pattern=p, width=.12, transition=.05) for p in ('line', 'square', 'triangle', 'hexagon')] + \
        [dict(BASE, kind='dots', pattern=p, width=.6, transition=.1) for p in ('square', 'triangle', 'hexagon')] + \
        [dict(BASE, kind='cellular', pattern='', type=t, cellWidth=.6, transWidth=.3, freqs=3, freqRatio=2.0, ampRatio=.5, variation=.4)
         for t in ('round', 'angular')] + \
        [dict(BASE, kind='wood', pattern='', ringScale=.25, wave=.5, waveScale=1.0, grain=.5, grainScale=.1, bias=.4, gain=.6),
         dict(BASE, kind='weave', pattern='', yarnWidth=.6, roundness=.6),
         dict(BASE, kind='ripples', pattern='', sources=8, wavelength=.2, phase=.25)]


class ProceduralBakeNative(unittest.TestCase):
    def test_the_adapter_bakes_as_python_samples(self):
        held = adapter()
        if held is None:
            self.skipTest('geometry adapter with MR_procedural_bake not built')
        resolution = 24
        for data in CASES:
            settings = procedurals.native_settings(data)
            numbers = (ctypes.c_double * len(settings))(*settings)
            rgb = (ctypes.c_float * (3 * resolution * resolution))()
            alpha = (ctypes.c_float * (3 * resolution * resolution))()
            self.assertEqual(held.MR_procedural_bake(numbers, len(settings), resolution, rgb, alpha, 2), 0, data['kind'])
            for y in range(resolution):
                for x in range(resolution):
                    colour, coverage = procedurals.sample(data, (x + .5) / resolution, (y + .5) / resolution)
                    at = 3 * (y * resolution + x)
                    for c in range(3):
                        self.assertAlmostEqual(rgb[at + c], colour[c], delta=1e-5, msg='%s %s at %d,%d' % (data['kind'], data['pattern'], x, y))
                    self.assertAlmostEqual(alpha[at], coverage, delta=1e-5, msg='%s alpha at %d,%d' % (data['kind'], x, y))

    def test_the_kit_s_bake_writes_the_same_images_either_way(self):
        # procedurals.bake through the adapter, and in Python (no adapter): the same two PFMs, to a float's last digits.
        held = adapter()
        if held is None:
            self.skipTest('geometry adapter with MR_procedural_bake not built')
        import tempfile
        from unittest import mock
        data = CASES[7]
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch('moonray_modo.procedurals.cache_root', return_value=pathlib.Path(folder) / 'a'), \
                    mock.patch('moonray_modo.rows._native', return_value=held):
                native = [p.read_bytes() for p in procedurals.bake(data, 32)]
            with mock.patch('moonray_modo.procedurals.cache_root', return_value=pathlib.Path(folder) / 'b'), \
                    mock.patch('moonray_modo.rows._native', return_value=None):
                python = [p.read_bytes() for p in procedurals.bake(data, 32)]
        for made, expected in zip(native, python):
            self.assertEqual(made.split(b'\n', 3)[:3], expected.split(b'\n', 3)[:3])
            a, b = array.array('f', made.split(b'\n', 3)[3]), array.array('f', expected.split(b'\n', 3)[3])
            self.assertEqual(len(a), len(b))
            self.assertLess(max(abs(x - y) for x, y in zip(a, b)), 1e-6)

    def test_settings_out_of_range_are_refused(self):
        held = adapter()
        if held is None:
            self.skipTest('geometry adapter with MR_procedural_bake not built')
        settings = procedurals.native_settings(CASES[0])
        settings[0] = 9
        numbers = (ctypes.c_double * len(settings))(*settings)
        out = (ctypes.c_float * 12)()
        self.assertEqual(held.MR_procedural_bake(numbers, len(settings), 2, out, out, 1), 1)


if __name__ == '__main__':
    unittest.main()
