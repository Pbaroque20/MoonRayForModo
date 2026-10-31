"""A package (.lpk) installed over an older kit (stale_files): only what the package names as left by earlier releases is
moved aside, once for each version, never deleted; everything else stays, and nothing happens outside the kit's own folder."""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import stale_files  # noqa: E402

INDEX = '<configuration kit="MoonRayForModo" version="0.5.1">\n'


class StaleFiles(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.kits = pathlib.Path(self.folder.name) / 'Kits'
        self.root = self.kits / 'MoonRayForModo'
        self.root.mkdir(parents=True)
        (self.root / 'index.cfg').write_text(INDEX)

    def tearDown(self):
        self.folder.cleanup()

    def put(self, *paths, root=None):
        for path in paths:
            target = (root or self.root) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(path)

    def package(self, superseded, root=None, version='0.5'):
        (root or self.root).joinpath('installed.txt').write_text(version + '\nindex.cfg\ninstalled.txt\n')
        (root or self.root).joinpath('superseded.txt').write_text('\n'.join(superseded) + '\n')

    def test_what_an_earlier_release_left_is_moved_aside(self):
        self.put('python/moonray_modo/old_module.py', 'runtime/old.dll')
        self.package(['python/moonray_modo/old_module.py', 'runtime/old.dll', 'runtime/gone_already.dll'])
        moved = stale_files.tidy(self.root)
        self.assertEqual(sorted(moved), ['python/moonray_modo/old_module.py', 'runtime/old.dll'])
        self.assertFalse((self.root / 'runtime/old.dll').exists())
        aside = list((self.root / '_replaced').iterdir())
        self.assertEqual(len(aside), 1)
        self.assertEqual((aside[0] / 'runtime/old.dll').read_text(), 'runtime/old.dll')

    def test_what_the_package_does_not_name_stays(self):
        # The user's own: a key map, the example scenes, a preset, anything else put there.
        kept = ('moonray_keys.cfg', 'runtime.json', 'layout.cfg', 'assets/library/MoonRay scenes/bedroom/scene.rdla',
                'assets/library/mine/preset.json', 'my_notes.txt', 'python/moonray_modo/__pycache__/panel.cpython-39.pyc')
        self.put(*kept, 'runtime/old.dll')
        self.package(['runtime/old.dll'])
        self.assertEqual(stale_files.tidy(self.root), ['runtime/old.dll'])
        for path in kept:
            self.assertTrue((self.root / path).is_file(), path)

    def test_never_outside_the_kit_folder_the_package_unpacked_into_kits_itself(self):
        # What happened: the kit's files in Kits, its other kits beside them. Kits is not the kit's folder.
        self.put('index.cfg', 'lxserv/tool.py', root=self.kits / 'ACS3')
        (self.kits / 'index.cfg').write_text(INDEX)
        self.package(['ACS3/index.cfg', 'ACS3/lxserv/tool.py', 'MoonRayForModo/index.cfg'], root=self.kits)
        self.assertEqual(stale_files.tidy(self.kits), [])
        self.assertTrue((self.kits / 'ACS3/index.cfg').is_file())
        self.assertFalse((self.kits / '_replaced').exists())

    def test_never_a_folder_with_another_kits_index(self):
        other = self.kits / 'MoonRayForModo2'
        self.put('index.cfg', 'old.py', root=other)
        self.package(['old.py'], root=other)
        self.assertEqual(stale_files.tidy(other), [])
        (self.root / 'index.cfg').write_text('<configuration kit="Another">\n')
        self.put('old.py')
        self.package(['old.py'])
        self.assertEqual(stale_files.tidy(self.root), [])
        self.assertTrue((self.root / 'old.py').is_file())

    def test_a_name_that_climbs_out_is_refused(self):
        self.put('index.cfg', root=self.kits / 'ACS3')
        self.package(['../ACS3/index.cfg', 'sub/../../ACS3/index.cfg', str(self.kits / 'ACS3/index.cfg').replace('\\', '/')])
        self.assertEqual(stale_files.tidy(self.root), [])
        self.assertTrue((self.kits / 'ACS3/index.cfg').is_file())

    def test_once_for_each_version(self):
        self.put('old.py')
        self.package(['old.py', 'later.py'])
        self.assertEqual(stale_files.tidy(self.root), ['old.py'])
        self.put('later.py')
        self.assertEqual(stale_files.tidy(self.root), [])
        self.assertTrue((self.root / 'later.py').is_file())

    def test_a_kit_not_from_a_package_is_left_alone(self):
        self.put('extra.py')
        self.assertEqual(stale_files.tidy(self.root), [])
        self.assertTrue((self.root / 'extra.py').is_file())
        (self.root / 'installed.txt').write_text('0.5\nindex.cfg\n')
        self.assertEqual(stale_files.tidy(self.root), [])
        self.assertTrue((self.root / 'extra.py').is_file())


class PackageList(unittest.TestCase):
    def test_every_file_goes_into_the_kits_own_folder(self):
        text = (ROOT / 'tools/package_lpk.py').read_text(encoding='utf-8')
        self.assertIn("quoteattr(PREFIX + path)", text)
        self.assertIn('restart="YES"', text)


if __name__ == '__main__':
    unittest.main()
