"""MoonLightIPR's Follow drags in the preview's preferences: off unless chosen (a drag is rendered once the mouse is let
go), the panel's live tick asking it, and the session holding a render at the press and taking it up at the release."""
import sys
import types
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
SOURCE = Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python/moonray_modo'

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


class Store(dict):
    def value(self, key, default=None):
        return self.get(key, default)


def read(stored):
    held = preferences.Preferences.__new__(preferences.Preferences)
    held.store = Store() if stored is None else Store({'moonlightipr/follow_drags': stored})
    return held.get('moonlightipr/follow_drags')


class FollowDrags(unittest.TestCase):
    def test_off_unless_chosen(self):
        self.assertIs(read(None), False)

    def test_chosen_on(self):
        self.assertIs(read('true'), True)
        self.assertIs(read('false'), False)

    def test_in_the_preferences_window(self):
        text = (SOURCE / 'preferences.py').read_text(encoding='utf-8')
        self.assertIn("check('moonlightipr/follow_drags', 'Follow drags'", text)

    def test_the_live_tick_asks_it(self):
        text = (SOURCE / 'panel.py').read_text(encoding='utf-8')
        self.assertIn("if held and ipr and not self._ipr_drags():", text)
        self.assertIn("self.preferences.get('moonlightipr/follow_drags')", text)
        self.assertNotIn('IPR_DRAGS=', text)

    def test_the_session_holds_and_takes_up(self):
        text = (SOURCE / 'moonlightipr_session.py').read_text(encoding='utf-8')
        self.assertIn("self.process.write(b'pause\\n')", text)
        self.assertIn("('continue %d\\n' % held)", text)


if __name__ == '__main__':
    unittest.main()
