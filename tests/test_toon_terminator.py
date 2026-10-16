"""The toon terminator preference: toon materials lit by their smooth normals on coarse meshes (issue 129).

MoonRay reads MOONRAY_MODO_TOON_TERMINATOR as it starts; the plugin sets it from the MoonRay preference, on by default."""
import os
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
from moonray_modo import native


class ToonTerminator(unittest.TestCase):
    def test_on_by_default(self):
        text = (KIT / 'python/moonray_modo/preferences.py').read_text(encoding='utf-8')
        self.assertIn("'toon_terminator': (True, bool)", text)

    def test_environment_carries_it(self):
        with mock.patch.object(native, 'toon_terminator', return_value=True):
            self.assertEqual(native.environment(ROOT)['MOONRAY_MODO_TOON_TERMINATOR'], '1')
        with mock.patch.object(native, 'toon_terminator', return_value=False):
            self.assertEqual(native.environment(ROOT)['MOONRAY_MODO_TOON_TERMINATOR'], '0')

    def test_outside_modo_follows_the_variable(self):
        with mock.patch.dict(sys.modules, {'PySide2': None}):
            with mock.patch.dict(os.environ, {'MOONRAY_MODO_TOON_TERMINATOR': '0'}):
                self.assertFalse(native.toon_terminator())
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop('MOONRAY_MODO_TOON_TERMINATOR', None)
                self.assertTrue(native.toon_terminator())

    def test_toon_albedo_reaches_moonray(self):
        text = (KIT / 'python/moonray_modo/preferences.py').read_text(encoding='utf-8')
        self.assertIn("'toon_albedo': (True, bool)", text)
        with mock.patch.object(native, 'toon_albedo', return_value=False):
            self.assertEqual(native.environment(ROOT)['MOONRAY_MODO_TOON_ALBEDO'], '0')
        with mock.patch.dict(sys.modules, {'PySide2': None}):
            with mock.patch.dict(os.environ, {'MOONRAY_MODO_TOON_ALBEDO': '1'}):
                self.assertTrue(native.toon_albedo())
        self.assertIn('cmd moonray.pref.toonAlbedo ?', (KIT / 'preferences.cfg').read_text(encoding='utf-8'))

    def test_on_the_preferences_page(self):
        page = (KIT / 'preferences.cfg').read_text(encoding='utf-8')
        self.assertIn('cmd moonray.pref.toonTerminator ?', page)
        commands = (KIT / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8')
        self.assertIn("lx.bless(switch('toon_terminator'),'moonray.pref.toonTerminator')", commands)


if __name__ == '__main__':
    unittest.main()
