"""Rhea's radiance cache (rhea/rhea_cache.h): the preference (in memory by default, or on disk), XPU2 told of it and of
its folder, the flush stamp the running XPU2 reads, Clear Radiance Cache and Clear Cache removing its files, and the
scene's close flushing what is held in memory."""
import shutil
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
SOURCE = ROOT / 'kit/MoonRayForModo/python/moonray_modo'
from moonray_modo import cache_folder, native  # noqa: E402

try:
    from moonray_modo import preferences
except ImportError:
    # Without Qt: only what the module names when it is read (as test_moonlightipr_follow_drags does), taken away at once.
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

FOLDER = ROOT / 'build' / 'test-rhea-cache'


class Store(dict):
    def value(self, key, default=None):
        return self.get(key, default)


class RheaCache(unittest.TestCase):
    def setUp(self):
        shutil.rmtree(FOLDER, ignore_errors=True)
        cache_folder.forget()
        cache_folder._HELD['root'] = FOLDER

    def tearDown(self):
        cache_folder.forget()
        shutil.rmtree(FOLDER, ignore_errors=True)

    def test_in_memory_unless_chosen(self):
        held = preferences.Preferences.__new__(preferences.Preferences)
        held.store = Store()
        self.assertEqual(held.get('xpu2/rhea_cache'), 'memory')
        held.store = Store({'xpu2/rhea_cache': 'disk'})
        self.assertEqual(held.get('xpu2/rhea_cache'), 'disk')
        self.assertEqual(dict(preferences.RHEA_CACHE_CHOICES), {'In memory': 'memory', 'On disk': 'disk'})
        for stored, expected in ((None, 'memory'), ('disk', 'disk'), ('memory', 'memory'), ('elsewhere', 'memory')):
            with mock.patch.object(native, '_setting', lambda key, default, s=stored: default if s is None else s):
                self.assertEqual(native.xpu2_rhea_cache(), expected)

    def test_xpu2_is_told(self):
        with mock.patch.object(native, 'xpu2_rhea_cache', return_value='disk'):
            env = native.xpu2_environment(ROOT / 'build')
        self.assertEqual(env['XPU2_SESSION_RHEA_CACHE'], 'disk')
        self.assertEqual(env['XPU2_SESSION_RHEA_CACHE_FOLDER'], str(FOLDER / 'Rhea'))
        # Another choice starts XPU2 again (it reads the choice as it starts).
        with mock.patch.object(native, 'xpu2_rhea_cache', return_value='disk'):
            disk = native.source_switches()
        with mock.patch.object(native, 'xpu2_rhea_cache', return_value='memory'):
            memory = native.source_switches()
        self.assertNotEqual(disk, memory)

    def test_flush_stamp(self):
        self.assertTrue(cache_folder.rhea_flush())
        first = (FOLDER / 'Rhea' / 'flush.stamp').read_text(encoding='ascii')
        self.assertTrue(first.strip().endswith('memory'))
        self.assertTrue(cache_folder.rhea_flush('clear'))
        second = (FOLDER / 'Rhea' / 'flush.stamp').read_text(encoding='ascii')
        self.assertTrue(second.strip().endswith('clear'))
        self.assertNotEqual(first, second)
        self.assertEqual(list((FOLDER / 'Rhea').glob('*.tmp')), [])

    def test_clear_radiance_cache(self):
        folder = FOLDER / 'Rhea'
        folder.mkdir(parents=True)
        (folder / ('a' * 32 + '.rhea')).write_bytes(b'x' * 1000)
        (folder / ('b' * 32 + '.rhea')).write_bytes(b'y' * 500)
        (FOLDER / 'Scenes').mkdir()
        (FOLDER / 'Scenes' / 'kept.bin').write_bytes(b'z')
        self.assertEqual(cache_folder.rhea_files(), (2, 1500))
        removed, freed, left = cache_folder.rhea_clear()
        self.assertEqual((removed, freed, left), (2, 1500, 0))
        self.assertEqual(cache_folder.rhea_files(), (0, 0))
        # The running XPU2 told to drop what it holds without writing it again; the scene cache left alone.
        self.assertTrue((folder / 'flush.stamp').read_text(encoding='ascii').strip().endswith('clear'))
        self.assertTrue((FOLDER / 'Scenes' / 'kept.bin').is_file())

    def test_clear_cache_includes_it(self):
        self.assertIn('Rhea', cache_folder.CLEARED)
        folder = FOLDER / 'Rhea'
        folder.mkdir(parents=True)
        (folder / ('c' * 32 + '.rhea')).write_bytes(b'x' * 100)
        removed, freed, _ = cache_folder.clear()
        self.assertGreaterEqual(removed, 1)
        self.assertEqual(cache_folder.rhea_files(), (0, 0))
        self.assertTrue((folder / 'flush.stamp').read_text(encoding='ascii').strip().endswith('clear'))

    def test_in_the_preferences_window(self):
        text = (SOURCE / 'preferences.py').read_text(encoding='utf-8')
        self.assertIn("combo('xpu2/rhea_cache', RHEA_CACHE_CHOICES", text)
        self.assertIn("'Rhea radiance cache'", text)
        self.assertIn("'Clear Radiance Cache' if on_disk else 'Flush Radiance Cache'", text)
        self.assertIn('cache_folder.rhea_clear()', text)
        self.assertIn("cache_folder.rhea_flush('memory')", text)

    def test_the_scene_closing_flushes_it(self):
        text = (SOURCE / 'panel.py').read_text(encoding='utf-8')
        closed = text[text.index('    def _scene_closed(self):'):]
        closed = closed[:closed.index('\n    def ', 10)]
        self.assertIn('self.renderer.release_engines()', closed)
        self.assertIn("cache_folder.rhea_flush('memory')", closed)


if __name__ == '__main__':
    unittest.main()
