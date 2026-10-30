"""Replacing a packaged asset must not write through its shared hard link."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import package_store

class PackageStore(unittest.TestCase):
    def test_replacement_preserves_store_and_other_packages(self):
        for shared in (False, True):
            with self.subTest(shared=shared), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                old = root / 'old.tx'; old.write_bytes(b'original')
                new = root / 'new.tx'; new.write_bytes(b'new version')
                store = root / 'store'
                a, b = root / 'a.tx', root / 'b.tx'
                digest = package_store.copy(old, a, store)
                package_store.copy(old, b, store)
                package_store.copy(new, a, store if shared else None)
                self.assertEqual(a.read_bytes(), b'new version')
                self.assertEqual(b.read_bytes(), b'original')
                self.assertEqual((store / (digest + '.tx')).read_bytes(), b'original')

    def test_repeated_copy_to_same_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.tx'; source.write_bytes(b'original')
            target = root / 'target.tx'
            digest = package_store.copy(source, target, root / 'store')
            self.assertEqual(package_store.copy(source, target, root / 'store'), digest)
            self.assertEqual(target.read_bytes(), b'original')

    def test_changed_source_during_copy_preserves_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.tx'; source.write_bytes(b'original')
            target = root / 'target.tx'; target.write_bytes(b'previous output')
            def changed_copy(source_name, destination_name):
                Path(destination_name).write_bytes(b'changed during copy')
            with mock.patch.object(package_store.shutil, 'copy2', side_effect=changed_copy):
                with self.assertRaisesRegex(ValueError, 'changed while packaging'):
                    package_store.copy(source, target)
            self.assertEqual(target.read_bytes(), b'previous output')
            # By name: some Pythons list the folder with another separator than the one it was named with.
            self.assertEqual({entry.name for entry in root.iterdir()}, {source.name, target.name})

    def test_copy_fallback_and_failed_publish(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'source.tx'; source.write_bytes(b'original')
            target = root / 'target.tx'
            store = root / 'store'
            with mock.patch.object(package_store.os, 'link', side_effect=OSError('no hard links')):
                package_store.copy(source, target, store)
            self.assertEqual(target.read_bytes(), b'original')
            source.write_bytes(b'new version')
            # Populate the cache first, so the injected failure is publication only.
            package_store.copy(source, root / 'other.tx', store)
            with mock.patch.object(Path, 'replace', side_effect=PermissionError('output locked')):
                with self.assertRaisesRegex(PermissionError, 'output locked'):
                    package_store.copy(source, target, store)
            self.assertEqual(target.read_bytes(), b'original')
            self.assertEqual(list(root.glob('*.partial')), [])
            self.assertEqual(list(store.glob('*.partial')), [])

if __name__ == '__main__':
    unittest.main()
