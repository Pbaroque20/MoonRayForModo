"""MoonLightIPR's sample levels in the preview's preferences: 128 to 1024, and what was stored before lifted to them."""
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


def read(stored):
    held = preferences.Preferences.__new__(preferences.Preferences)
    held.store = Store() if stored is None else Store({'moonlightipr/samples': stored})
    return held.get('moonlightipr/samples')


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


if __name__ == '__main__':
    unittest.main()
