"""The Ocean folder kept within its size: a sea's tiles are made for each moment it is rendered at, some 50 MB a moment,
and a tester's animated seas came to 32 GB in a day with nothing let go, filling the disk. Looked over as tiles are made,
the least lately used let go first; a tile used again is marked as lately used, with what MoonLightIPR made ready of it
beside it; Clear Cache empties the folder too."""
import os
import pathlib
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import cache_folder, ocean  # noqa: E402


class OceanCache(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.base = pathlib.Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def file(self, name, size, age):
        path = self.base / name
        path.write_bytes(b'x' * size)
        moment = time.time() - age
        os.utime(path, (moment, moment))
        return path

    def test_the_folder_is_brought_under_its_limit_the_oldest_first(self):
        old = self.file('a.displacement.pfm', 400, 300)
        older = self.file('b.displacement.pfm', 400, 600)
        new = self.file('c.displacement.pfm', 400, 10)
        freed = ocean.trim(self.base, limit=900)
        self.assertEqual(freed, 400)
        self.assertFalse(older.exists())
        self.assertTrue(old.exists() and new.exists())

    def test_nothing_is_let_go_within_the_limit(self):
        self.file('a.foam.pfm', 100, 100)
        self.assertEqual(ocean.trim(self.base, limit=1000), 0)
        self.assertEqual(len(list(self.base.iterdir())), 1)

    def test_a_tile_used_again_is_kept_before_older_ones_with_what_moonlightipr_made_of_it(self):
        used = self.file('a.displacement.pfm', 400, 900)
        ready = self.file('a.displacement.pfm.mlt', 400, 900)
        other = self.file('b.displacement.pfm', 400, 300)
        ocean.used([used])
        ocean.trim(self.base, limit=800)
        self.assertTrue(used.exists() and ready.exists())
        self.assertFalse(other.exists())

    def test_tiles_found_on_disk_are_used_again_and_marked(self):
        value = dict(ocean.DEFAULTS, resolution=16)
        with mock.patch('moonray_modo.ocean.folder', return_value=self.base):
            made = ocean.paths(value, 1.0)
            for path in made:
                path.write_bytes(b'pfm')
                os.utime(path, (1.0, 1.0))
            with mock.patch('moonray_modo.ocean.native_tile', side_effect=AssertionError('made again')):
                self.assertEqual(ocean.make(value, 1.0), made)
        self.assertTrue(all(path.stat().st_mtime > 1000 for path in made))

    def test_making_a_tile_looks_the_folder_over(self):
        with mock.patch('moonray_modo.ocean.trim') as trimmed:
            ocean._MADE[0] = 0
            ocean._made()
            self.assertEqual(trimmed.call_count, 1)
            for _ in range(ocean.TRIM_EVERY - 1):
                ocean._made()
            self.assertEqual(trimmed.call_count, 1)
            ocean._made()
            self.assertEqual(trimmed.call_count, 2)

    def test_clear_cache_empties_the_ocean_folder(self):
        cache_folder.forget()
        cache_folder._HELD.update(root=self.base, scene=True)
        try:
            (self.base / 'Ocean').mkdir()
            (self.base / 'Ocean' / 'a.displacement.pfm').write_bytes(b'x' * 50)
            removed, freed, left = cache_folder.clear()
            self.assertEqual((removed, freed, left), (1, 50, 0))
            self.assertFalse((self.base / 'Ocean').exists())
        finally:
            cache_folder.forget()


if __name__ == '__main__':
    unittest.main()
