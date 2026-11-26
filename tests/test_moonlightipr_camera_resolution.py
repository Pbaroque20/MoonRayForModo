"""A MoonLightIPR Render (RT off) is made at the active camera's resolution unless the preview's preferences say otherwise:
on by default (it was opt-in); a user who switched it off keeps it off."""
import sys
import types
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))

try:
    from moonray_modo import preferences
except ImportError:
    # Without Qt: only what the module names when it is read (as test_moonlightipr_samples does), taken away at once.
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

KEY = 'moonlightipr/camera_resolution'


class Store(dict):
    def value(self, key, default=None):
        return self.get(key, default)


def read(stored):
    held = preferences.Preferences.__new__(preferences.Preferences)
    held.store = Store() if stored is None else Store({KEY: stored})
    return held.get(KEY)


class CameraResolution(unittest.TestCase):
    def test_on_unless_chosen_otherwise(self):
        self.assertIs(read(None), True)

    def test_a_choice_kept(self):
        self.assertIs(read('false'), False)
        self.assertIs(read('true'), True)


if __name__ == '__main__':
    unittest.main()
