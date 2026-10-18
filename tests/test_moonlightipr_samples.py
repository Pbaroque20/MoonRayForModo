"""The realtime engines' sample levels in the preview's preferences, MoonLightIPR's 128 to 1024 and MoonRay LS's 32 to 128,
and what was stored before lifted to them."""
import sys
import types
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))

try:
    from moonray_modo import preferences
except ImportError:
    # Without Qt: only what the module names when it is read, nothing of Qt being used here. The stand-in is taken
    # away again at once, so that other tests still find Qt missing and skip as they do.
    qt = types.ModuleType('PySide2')
    qt.QtCore = types.SimpleNamespace(QSettings=None)
    qt.QtWidgets = types.SimpleNamespace(QDialog=object)
    sys.modules['PySide2'] = qt
    try:
        from moonray_modo import preferences
    finally:
        del sys.modules['PySide2']
        sys.modules.pop('moonray_modo.preferences', None)
        vars(sys.modules['moonray_modo']).pop('preferences', None)


class Store(dict):
    def value(self, key, default=None):
        return self.get(key, default)


def read(stored, key='moonlightipr/samples'):
    held = preferences.Preferences.__new__(preferences.Preferences)
    held.store = Store() if stored is None else Store({key: stored})
    return held.get(key)


class Samples(unittest.TestCase):
    def test_the_levels(self):
        self.assertEqual(preferences.MOONLIGHTIPR_SAMPLES, (128, 256, 512, 1024))

    def test_the_default_is_one_of_them(self):
        self.assertEqual(read(None), 256)

    def test_fewer_than_128_stored_before_is_128(self):
        self.assertEqual(read('32'), 128)
        self.assertEqual(read(64), 128)

    def test_a_level_is_kept(self):
        for level in preferences.MOONLIGHTIPR_SAMPLES:
            self.assertEqual(read(str(level)), level)


class LowSamples(unittest.TestCase):
    def test_the_levels(self):
        self.assertEqual(preferences.LS_SAMPLES, (32, 64, 128))

    def test_the_default_is_the_fewest(self):
        self.assertEqual(read(None, 'ipr/samples'), 32)

    def test_fewer_than_32_stored_before_is_32(self):
        for stored in ('1', '4', 16):
            self.assertEqual(read(stored, 'ipr/samples'), 32)

    def test_a_level_is_kept(self):
        for level in preferences.LS_SAMPLES:
            self.assertEqual(read(str(level), 'ipr/samples'), level)

    def test_moonray_ls_takes_128(self):
        from moonray_modo.ipr import prepare
        scene = {'width': 640, 'height': 360, 'render_settings': {'sampling_mode': 2, 'max_adaptive_samples': 1024}}
        prepared, _, _ = prepare(scene, 640, 360, 4, 640, 128)
        self.assertEqual(prepared['render_settings']['max_adaptive_samples'], 128)


class DraftWidth(unittest.TestCase):
    def test_the_widths(self):
        self.assertEqual(preferences.DRAFT_WIDTHS, (320, 640, 1280))

    def test_the_default_is_640(self):
        self.assertEqual(read(None, 'draft/width'), 640.0)

    def test_a_width_typed_before_is_the_nearest(self):
        for stored, nearest in (('64', 320.0), (500, 640.0), ('900', 640.0), ('1000', 1280.0), (3200, 1280.0)):
            self.assertEqual(read(stored, 'draft/width'), nearest)


if __name__ == '__main__':
    unittest.main()
