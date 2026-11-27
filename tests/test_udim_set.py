"""A file chosen in the graph editor that is one tile of a UDIM set (textures.udim_set): its <UDIM> pattern and tiles."""
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import textures  # noqa: E402


class UdimSet(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp())

    def make(self, *names):
        for name in names:
            (self.folder / name).write_bytes(b'x')

    def test_a_tile_gives_its_set(self):
        self.make('body.1001.exr', 'body.1002.exr', 'body.1011.exr', 'head.1001.exr')
        pattern, tiles = textures.udim_set(self.folder / 'body.1002.exr')
        self.assertTrue(pattern.endswith('/body.<UDIM>.exr'), pattern)
        self.assertEqual(tiles, [1001, 1002, 1011])
        self.assertNotIn('\\', pattern)

    def test_a_file_alone_stays_a_file(self):
        self.make('body.1001.exr', 'other.1002.exr')
        self.assertIsNone(textures.udim_set(self.folder / 'body.1001.exr'))

    def test_numbers_inside_longer_ones_and_outside_the_range(self):
        self.make('scan_21001.png', 'scan_21002.png', 'shot_0999.png', 'shot_1000.png', 'shot_2000.png', 'shot_2001.png')
        self.assertIsNone(textures.udim_set(self.folder / 'scan_21001.png'))
        self.assertIsNone(textures.udim_set(self.folder / 'shot_2000.png'))

    def test_the_run_with_the_most_tiles(self):
        # A version number that looks like a tile: v1001 is the same in every file, the tile number changes.
        self.make('wall_1001_1001.tx', 'wall_1001_1002.tx', 'wall_1001_1003.tx')
        pattern, tiles = textures.udim_set(self.folder / 'wall_1001_1002.tx')
        self.assertTrue(pattern.endswith('/wall_1001_<UDIM>.tx'), pattern)
        self.assertEqual(tiles, [1001, 1002, 1003])

    def test_a_pattern_already(self):
        self.make('body.1001.exr', 'body.1002.exr')
        self.assertIsNone(textures.udim_set(str(self.folder / 'body.<UDIM>.exr')))

    def test_the_pattern_finds_the_tiles_again(self):
        self.make('rock_1001.jpg', 'rock_1002.jpg')
        pattern, tiles = textures.udim_set(self.folder / 'rock_1001.jpg')
        self.assertEqual(sorted(textures.source_tiles(pattern)), tiles)


if __name__ == '__main__':
    unittest.main()
