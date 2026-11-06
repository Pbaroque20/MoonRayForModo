"""The fur surface read by the geometry adapter (native-modo/fur_reader.cpp, fur_reader.read): what it writes reads
as the lists fur.py walks (fur_reader.Flat), and the native grower's request takes its runs as they are. In Modo the
two readings hand the grower the same triangles, maps and guides (tools/probe_cl_fur_native_read.py: a 200,000-polygon
pelt in 0.9 s rather than 6.9 s)."""
import struct
import sys
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import fur, fur_native, fur_reader  # noqa: E402

FLOOR = [((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 1, 0), (0, 1, 0), (0, 1, 0)), ((0, 0, 0), (1, 0, 1), (0, 0, 1), (0, 1, 0), (0, 1, 0), (0, 1, 0))]


def written():
    """The file MR_fur_surface would write for FLOOR: two triangles of one material, a weight map and a guide."""
    data = [b'MFS1', struct.pack('<i', 2), array('d', [v for t in FLOOR for p in t for v in p]).tobytes(),
            struct.pack('<i', 1), struct.pack('<i', 4), b'Skin', struct.pack('<2i', 0, 0),
            struct.pack('<i', 1), array('d', [.5, .5, .5, 1, 1, 1]).tobytes(),
            struct.pack('<i', 0),
            struct.pack('<i', 1), struct.pack('<i', 2), array('d', [.5, 0, .5, .5, .3, .5]).tobytes()]
    return b''.join(data)


class FlatRuns(unittest.TestCase):
    def test_reads_as_the_lists_fur_walks(self):
        got = fur_reader._parse(written(), ['Lengths'], False)
        self.assertEqual([tuple(map(tuple, t)) for t in FLOOR], list(got['triangles']))
        self.assertEqual(got['worn'], ['Skin', 'Skin'])
        self.assertEqual(list(got['weights']['Lengths']), [(.5, .5, .5), (1.0, 1.0, 1.0)])
        self.assertEqual(got['guides'], [[[.5, 0.0, .5], [.5, .3, .5]]])

    def test_the_same_fur_and_request_either_way(self):
        got = fur_reader._parse(written(), ['Lengths'], False)
        held = dict(fur.CHANNELS, dist=.05)
        maps = {'length': got['weights']['Lengths']}
        listed = {'length': [(.5, .5, .5), (1.0, 1.0, 1.0)]}
        self.assertEqual(fur.grow(got['triangles'], held, maps)[0], fur.grow(FLOOR, held, listed)[0])
        self.assertEqual(fur_native.request(got['triangles'], held, maps, [0, 0]), fur_native.request(FLOOR, held, listed, [0, 0]))


if __name__ == '__main__':
    unittest.main()
