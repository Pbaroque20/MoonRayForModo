"""A runtime's programs (maketx.exe, oiiotool.exe) found where they are (native.tool): in the runtime given first, then
the kit's own, each with the folder above it and its bin; and a plain word naming where it looked when none has it (a
tester was told to reinstall while maketx stood in the runtime chosen)."""
import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import native  # noqa: E402


class RuntimeTools(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def place(self, *parts):
        path = self.root.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'')
        return path

    def test_found_in_the_runtime_given(self):
        tool = self.place('chosen', 'maketx.exe')
        with patch.object(native, 'default_runtime', return_value=''):
            self.assertEqual(native.tool('maketx.exe', str(self.root / 'chosen')), tool)

    def test_found_beside_moonray_in_its_bin(self):
        tool = self.place('release', 'bin', 'maketx.exe')
        with patch.object(native, 'default_runtime', return_value=''):
            self.assertEqual(native.tool('maketx.exe', str(self.root / 'release')), tool)
            self.assertEqual(native.tool('maketx.exe', str(self.root / 'release' / 'moonray.exe')), tool)

    def test_the_kits_own_after_the_one_given(self):
        tool = self.place('kit', 'oiiotool.exe')
        with patch.object(native, 'default_runtime', return_value=str(self.root / 'kit')):
            self.assertEqual(native.tool('oiiotool.exe', str(self.root / 'empty')), tool)

    def test_says_where_it_looked(self):
        with patch.object(native, 'default_runtime', return_value=str(self.root / 'kit')):
            with self.assertRaises(ValueError) as said:
                native.tool('maketx.exe', str(self.root / 'chosen'))
        self.assertIn('maketx.exe was not found', str(said.exception))
        self.assertIn(str(self.root / 'chosen'), str(said.exception))
        self.assertIn(str(self.root / 'kit'), str(said.exception))


if __name__ == '__main__':
    unittest.main()
