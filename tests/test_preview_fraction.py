"""The realtime preview's resolution as a share of the render's (Realtime preview resolution: full, a half, a third, a
quarter), and a width in pixels chosen before taken to the nearest share of a 1920-wide render."""
import sys
import types
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))

try:
    from moonray_modo import preferences
except ImportError:
    # Without Qt, as test_moonlightipr_samples.py does: only names, the stand-in taken away again at once.
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


def read(**stored):
    held = preferences.Preferences.__new__(preferences.Preferences)
    held.store = Store(stored)
    return held.get('preview_fraction')


class PreviewFraction(unittest.TestCase):
    def test_the_choices(self):
        self.assertEqual([value for _, value in preferences.FRACTIONS], [1, 2, 3, 4, 8, 16])

    def test_a_third_where_nothing_was_chosen(self):
        self.assertEqual(read(), 3)

    def test_a_width_chosen_before_becomes_the_nearest_share(self):
        self.assertEqual(read(preview_size='640'), 3)
        self.assertEqual(read(preview_size=960), 2)
        self.assertEqual(read(preview_size='1280'), 2)
        self.assertEqual(read(preview_size='320'), 4)

    def test_a_share_chosen_is_kept(self):
        for value in (1, 2, 3, 4, 8, 16):
            self.assertEqual(read(preview_fraction=str(value), preview_size='320'), value)

    def test_nonsense_is_taken_as_not_chosen(self):
        self.assertEqual(read(preview_fraction='7', preview_size='960'), 2)
        self.assertEqual(read(preview_size='wide'), 3)


if __name__ == '__main__':
    unittest.main()
