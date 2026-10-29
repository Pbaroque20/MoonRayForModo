"""A package (.lpk) installed over an older kit (stale_files): what the older version left and the package's list does
not name is moved aside, once for each version, never deleted; the user's own files and Python's caches stay; a kit
not installed from a package is left as it is."""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import stale_files  # noqa: E402


class StaleFiles(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def put(self, *paths):
        for path in paths:
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(path)

    def test_what_the_older_version_left_is_moved_aside(self):
        self.put('index.cfg', 'python/moonray_modo/panel.py', 'python/moonray_modo/old_module.py', 'runtime/old.dll',
                 'runtime.json', 'layout.cfg', 'python/moonray_modo/__pycache__/panel.cpython-39.pyc')
        (self.root / 'installed.txt').write_text('0.5\nindex.cfg\npython/moonray_modo/panel.py\ninstalled.txt\n')
        moved = stale_files.tidy(self.root)
        self.assertEqual(sorted(moved), ['python/moonray_modo/old_module.py', 'runtime/old.dll'])
        self.assertFalse((self.root / 'runtime/old.dll').exists())
        aside = list((self.root / '_replaced').iterdir())
        self.assertEqual(len(aside), 1)
        self.assertEqual((aside[0] / 'runtime/old.dll').read_text(), 'runtime/old.dll')
        for kept in ('index.cfg', 'python/moonray_modo/panel.py', 'runtime.json', 'layout.cfg',
                     'python/moonray_modo/__pycache__/panel.cpython-39.pyc'):
            self.assertTrue((self.root / kept).is_file(), kept)

    def test_once_for_each_version(self):
        self.put('index.cfg')
        (self.root / 'installed.txt').write_text('0.5\nindex.cfg\ninstalled.txt\n')
        stale_files.tidy(self.root)
        self.put('later.py')
        self.assertEqual(stale_files.tidy(self.root), [])
        self.assertTrue((self.root / 'later.py').is_file())

    def test_a_kit_not_from_a_package_is_left_alone(self):
        self.put('index.cfg', 'extra.py')
        self.assertEqual(stale_files.tidy(self.root), [])
        self.assertTrue((self.root / 'extra.py').is_file())


if __name__ == '__main__':
    unittest.main()
