"""The build number the About window shows: what the kit was stamped with, and "unknown" for a kit that never was."""
import pathlib
import re
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
sys.path.insert(0, str(ROOT / 'tools'))
import moonray_modo
import build_number


class BuildNumber(unittest.TestCase):
    def test_reads_the_stamp(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'BUILD.txt'
            path.write_text('1195+\n', encoding='ascii')
            with mock.patch.object(moonray_modo, '_BUILD_FILE', path):
                self.assertEqual(moonray_modo.build_number(), '1195+')

    def test_unstamped_kit(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.object(moonray_modo, '_BUILD_FILE', pathlib.Path(folder) / 'BUILD.txt'):
                self.assertEqual(moonray_modo.build_number(), 'unknown')

    def test_stamp_is_commits_so_far(self):
        self.assertRegex(build_number.number(), r'^\d+\+?$')

    def test_about_says_it_after_the_version(self):
        text = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/about.py').read_text(encoding='utf-8')
        self.assertTrue(re.search(r"Version '\+__version__\+' · Build '\+build_number\(\)\+", text))


if __name__ == '__main__':
    unittest.main()
