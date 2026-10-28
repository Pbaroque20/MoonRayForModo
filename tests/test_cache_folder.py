"""The Cache folder: the kit's caches under it, %LOCALAPPDATA%\\MoonRayForModo where none is chosen, and the renderers
told of it (MOONRAY_MODO_CACHE)."""
import os
import pathlib
import sys
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import cache_folder, native, texture_cache


class CacheFolder(unittest.TestCase):
    def tearDown(self):
        cache_folder.forget()

    def test_none_chosen_is_in_the_profile(self):
        cache_folder.forget()
        with patch.dict(os.environ, {'LOCALAPPDATA': str(ROOT / 'build')}):
            self.assertEqual(cache_folder.root(), ROOT / 'build' / 'MoonRayForModo')

    def test_the_caches_and_the_renderers_follow_the_folder(self):
        cache_folder.forget()
        cache_folder._HELD['root'] = ROOT / 'build' / 'chosen-cache'
        self.assertEqual(texture_cache.root(), (ROOT / 'build' / 'chosen-cache' / 'Textures').resolve())
        self.assertEqual(native.environment(ROOT / 'build')['MOONRAY_MODO_CACHE'], str(ROOT / 'build' / 'chosen-cache'))
        cache_folder.forget()
        self.assertEqual(cache_folder._HELD, {})


if __name__ == '__main__':
    unittest.main()
