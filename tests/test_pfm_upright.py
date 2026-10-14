import pathlib
import struct
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import pfm


class Upright(unittest.TestCase):
    def test_rows_written_top_first_are_put_bottom_first(self):
        width, height = 3, 4
        rows = [b''.join(struct.pack('<3f', y, x, 0) for x in range(width)) for y in range(height)]
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'picture.pfm'
            path.write_bytes(b'PF\n3 4\n-1.0\n' + b''.join(rows))
            pfm.upright(str(path))
            data = path.read_bytes()
            channels, w, h, start = pfm.header(data)
            self.assertEqual((channels, w, h), (3, width, height))
            self.assertEqual(data[start:], b''.join(reversed(rows)))

    def test_a_file_of_the_wrong_size_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            path = pathlib.Path(folder) / 'short.pfm'
            path.write_bytes(b'PF\n3 4\n-1.0\n' + b'\0' * 12)
            with self.assertRaises(ValueError):
                pfm.upright(str(path))


if __name__ == '__main__':
    unittest.main()
