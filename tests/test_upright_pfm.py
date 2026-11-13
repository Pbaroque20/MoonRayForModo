"""Large float images the right way up for MoonLightIPR (moonlightipr_materials._pfm_bands, _turn_pfm): oiiotool wrote
an 8K EXR's PFM upside down at its full size (a Render's HDRI flipped against realtime's); the kit compares its top and
bottom with a small copy's and turns its rows over."""
import pathlib
import struct
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_materials as mm  # noqa: E402


def write(path, rows):
    """A colour PFM of these rows, given top first; each row a list of grey values."""
    width, height = len(rows[0]), len(rows)
    body = b''.join(struct.pack('<%df' % (width * 3), *[v for value in row for v in (value, value, value)]) for row in reversed(rows))
    path.write_bytes(('PF\n%d %d\n-1.0\n' % (width, height)).encode() + body)


class Upright(unittest.TestCase):
    def test_bands_read_bottom_and_top_as_the_picture_stands(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'sky.pfm'
            write(path, [[1.0] * 4] * 32 + [[0.1] * 4] * 32)     # bright sky above dark ground
            bottom, top = mm._pfm_bands(path)
            self.assertAlmostEqual(bottom, 0.1, places=5)
            self.assertAlmostEqual(top, 1.0, places=5)

    def test_turned_over_its_top_is_its_bottom(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'sky.pfm'
            rows = [[float(y)] * 3 for y in range(8)]
            write(path, rows)
            before = path.read_bytes()
            mm._turn_pfm(path)
            bottom, top = mm._pfm_bands(path)
            self.assertEqual((bottom, top), (0.0, 7.0))
            mm._turn_pfm(path)
            self.assertEqual(path.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
