"""MoonRay is started with a PATH of folders only: an entry that is a file (cmd.exe) stopped it with "directory iterator
cannot open directory: Not a directory". And the MoonRay Source Override for the same look (MOONRAY_MODO_DSO_SEARCH)."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import native


class Folders(unittest.TestCase):
    def test_files_and_missing_entries_are_dropped_in_order(self):
        with tempfile.TemporaryDirectory() as folder:
            first, second = Path(folder) / 'a', Path(folder) / 'b'
            first.mkdir(); second.mkdir()
            program = Path(folder) / 'cmd.exe'
            program.write_bytes(b'')
            path = os.pathsep.join([str(first), str(program), '', str(Path(folder) / 'gone'), '"%s"' % second])
            self.assertEqual(native.folders_only(path), os.pathsep.join([str(first), '"%s"' % second]))

    def test_moonray_gets_the_runtime_then_folders(self):
        with tempfile.TemporaryDirectory() as folder:
            program = Path(folder) / 'cmd.exe'
            program.write_bytes(b'')
            with mock.patch.dict(os.environ, {'PATH': os.pathsep.join([str(program), folder])}), \
                    mock.patch.object(native, '_switch', lambda key, variable: True):
                env = native.environment(folder)
            self.assertEqual(env['PATH'].split(os.pathsep), [folder, folder])
            self.assertEqual(env['MOONRAY_MODO_DSO_SEARCH'], '1')

    def test_the_override_is_a_preference_with_a_checkbox(self):
        self.assertIn("'dso_search': (True, bool)", (ROOT / 'kit/MoonRayForModo/python/moonray_modo/preferences.py').read_text(encoding='utf-8'))
        self.assertIn('cmd moonray.pref.dsoSearch ?', (ROOT / 'kit/MoonRayForModo/preferences.cfg').read_text(encoding='utf-8'))
        self.assertIn("'moonray.pref.dsoSearch'", (ROOT / 'kit/MoonRayForModo/lxserv/moonray_preferences.py').read_text(encoding='utf-8'))
        self.assertIn('MOONRAY_MODO_DSO_SEARCH', (ROOT / 'patches/native-windows/scene_rdl2.patch').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
