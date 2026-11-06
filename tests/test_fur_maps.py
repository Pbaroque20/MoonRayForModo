"""The Fur material's vector map and width map (2026-11-05), as Modo's renderer draws them (tools/probe_cl_fur_maps.py,
test-results/fur-maps): each fibre grows along the vector map's vector at its root, as long as the vector, and none
grows where it is nothing; the width map's weight at a fibre's root scales its width. The native grower grows the
same fibres with the same radii."""
import math
import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import fur, fur_native  # noqa: E402

BUILT = ROOT / 'build/native-avx/bin/modo_fur_grow.exe'
FLOOR = [((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 1, 0), (0, 1, 0), (0, 1, 0)), ((0, 0, 0), (1, 0, 1), (0, 0, 1), (0, 1, 0), (0, 1, 0), (0, 1, 0))]
STILL = {'dist': .02, 'length': .1, 'flex': 0.0, 'growthJitter': 0.0, 'sclJitter': 0.0, 'nrmJitter': 0.0, 'strays': 0.0}


def everywhere(vector):
    return [(vector, vector, vector)] * len(FLOOR)


class VectorMap(unittest.TestCase):
    def test_fibres_grow_along_the_vector_and_as_long(self):
        strands = fur.grow(FLOOR, dict(STILL), {'vector': everywhere((.3, .3, 0.0))})[0]
        self.assertTrue(strands)
        for strand in strands[:40]:
            way = [strand[-1][k] - strand[0][k] for k in range(3)]
            self.assertAlmostEqual(math.sqrt(sum(v * v for v in way)), math.sqrt(.18), places=6)
            self.assertAlmostEqual(way[0], way[1], places=6)

    def test_none_grows_where_it_is_nothing(self):
        # The first triangle's corners leaning, the second's nothing: only the first grows fur.
        maps = {'vector': [((.3, .3, 0.0),) * 3, ((0.0, 0.0, 0.0),) * 3]}
        strands, _, _, _, stands, _ = fur.grow(FLOOR, dict(STILL), maps)
        self.assertTrue(strands)
        self.assertEqual(set(stands), {0})


class WidthMap(unittest.TestCase):
    def test_the_weight_is_each_fibres_share_of_the_width(self):
        maps = {'width': [(.25, .25, .25), (1.0, 1.0, 1.0)]}
        _, _, _, _, stands, widths = fur.grow(FLOOR, dict(STILL), maps)
        self.assertEqual({(s, w) for s, w in zip(stands, widths)}, {(0, .25), (1, 1.0)})
        self.assertEqual(set(fur.grow(FLOOR, dict(STILL))[5]), {1.0})


@unittest.skipUnless(BUILT.is_file(), 'modo_fur_grow.exe has not been built (tools/build_fur_grower.py)')
class NativeMaps(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp())
        self.was = fur_native.program, fur_native.folder
        fur_native.program = lambda runtime=None: BUILT
        fur_native.folder = lambda: self.home

    def tearDown(self):
        fur_native.program, fur_native.folder = self.was
        shutil.rmtree(str(self.home), ignore_errors=True)

    def test_the_same_fibres_and_radii_as_in_python(self):
        maps = {'vector': [((.2, .3, .05), (.1, .2, 0.0), (0.0, .25, .1)), ((.3, .1, 0.0), (0.0, 0.0, 0.0), (.1, .3, .1))],
                'width': [(.2, .6, 1.0), (1.0, .5, .3)]}
        held = dict(fur.CHANNELS, **dict(STILL, kinkAmp=.2, taper=.5))
        strands, root, tip, _, _, widths = fur.grow(FLOOR, held, maps)
        made = fur_native.grow(FLOOR, held, maps, [0, 0])
        self.assertIsNotNone(made)
        vertices, counts, radii, places, fibres = fur_native.read(made['files'][0][0])
        self.assertEqual((fibres, counts), (len(strands), [len(s) for s in strands]))
        flat = [p for s in strands for p in s]
        self.assertLess(max(abs(a - b) for p, q in zip(flat, vertices) for a, b in zip(p, q)), 1e-6)
        # Each fibre's root radius is the material's root radius times its width share.
        at = 0
        for strand, share in zip(strands, widths):
            self.assertAlmostEqual(radii[at], root * share, places=6)
            at += len(strand)


if __name__ == '__main__':
    unittest.main()
