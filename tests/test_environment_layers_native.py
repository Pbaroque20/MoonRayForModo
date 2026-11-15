"""Layered environments with Modo's physical sky and procedurals laid by the geometry adapter (MR_environment_layers,
environment_layers.native_blend) as the Python loop lays them: the same map, value by value. Needs the adapter built
(tools/build_modo_bridge.py)."""
import array
import ctypes
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import environment_layers  # noqa: E402


def adapter():
    for build in sorted((ROOT / 'build').glob('modo-geometry*/MoonRayGeometry.lx'), key=lambda p: -p.stat().st_mtime):
        try:
            held = ctypes.CDLL(str(build))
        except OSError:
            continue
        if hasattr(held, 'MR_environment_layers'):
            return held
    return None


def sky(**own):
    return dict({'kind': 'physical', 'effect': 'envColor', 'opacity': 1.0, 'blend': 'normal', 'invert': False, 'groups': [],
                 'sun_direction': [.3, .45, -.84], 'haze': 3.0}, **own)


PATTERN = {'kind': 'cellular', 'pattern': '', 'type': 'round', 'bias': .5, 'gain': .5, 'color1': [.9, .8, .7], 'color2': [.1, .2, .3],
           'alpha1': 1.0, 'alpha2': .3, 'cellWidth': .6, 'transWidth': .3, 'freqs': 2, 'freqRatio': 2.0, 'ampRatio': .5, 'variation': .2}
CASES = {
    'sky': [sky()],
    'sky with clouds of a procedural': [sky(), {'kind': 'procedural', 'effect': 'envColor', 'opacity': .6, 'blend': 'screen',
                                                'invert': False, 'groups': [], 'procedural': PATTERN, 'uv_matrix': [2, 0, 0, 0, 2, 0]}],
    'sky over another ground, clamped': [sky(ground_albedo=[.2, .4, .1], normalize=True, sky_gamma=2.2)],
}


class EnvironmentLayersNative(unittest.TestCase):
    def composed(self, layers, library, folder):
        with mock.patch('moonray_modo.environment_layers.cache_root', return_value=pathlib.Path(folder)), \
                mock.patch('moonray_modo.rows._native', return_value=library), \
                mock.patch('moonray_modo.textures.prepare', side_effect=lambda path, *a, **k: path):
            made = pathlib.Path(environment_layers.texture({'kind': 'stack', 'layers': layers}, 256, 128))
        return array.array('f', made.read_bytes().split(b'\n', 3)[3])

    def test_the_adapter_lays_skies_and_procedurals_as_python_does(self):
        held = adapter()
        if held is None:
            self.skipTest('geometry adapter with MR_environment_layers not built')
        for name, layers in CASES.items():
            with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
                laid = []
                real = environment_layers.native_blend
                with mock.patch('moonray_modo.environment_layers.native_layers', return_value=True), \
                        mock.patch('moonray_modo.environment_layers.native_blend', side_effect=lambda *x: laid.append(real(*x)) or laid[-1]):
                    native = self.composed(layers, held, a)
                self.assertTrue(laid and laid[0] is not None, name + ': not laid by the adapter')
                with mock.patch('moonray_modo.environment_layers.native_layers', return_value=False):
                    python = self.composed(layers, None, b)
            self.assertEqual(len(native), len(python), name)
            worst = max(abs(x - y) / max(1.0, abs(y)) for x, y in zip(native, python))
            self.assertLess(worst, 1e-5, name)

    def test_moonlightipr_takes_the_composed_image_not_a_tx(self):
        # MoonLightIPR makes its own image from the composed PFM: no .tx is asked for it, which it read before the
        # converter had made it ("[WinError 2]", a car's environment grey in realtime).
        layers = [{'kind': 'constant', 'effect': 'envColor', 'opacity': 1.0, 'blend': 'normal', 'invert': False, 'groups': [],
                   'zenith': [.2, .3, .4]}]
        with tempfile.TemporaryDirectory() as folder, \
                mock.patch('moonray_modo.environment_layers.cache_root', return_value=pathlib.Path(folder)), \
                mock.patch('moonray_modo.environment_layers.native_blend', return_value=None), \
                mock.patch('moonray_modo.textures.prepare', side_effect=AssertionError('a .tx asked for')):
            made = pathlib.Path(environment_layers.texture({'kind': 'stack', 'layers': layers}, 16, 8, renderer=False))
            self.assertEqual(made.suffix, '.pfm')
            self.assertTrue(made.is_file())


if __name__ == '__main__':
    unittest.main()
