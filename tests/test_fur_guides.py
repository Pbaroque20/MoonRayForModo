"""Fur guides (2026-11-05), as Modo's renderer draws them (tools/probe_cl_fur_guides.py, test-results/fur-guides*):
Direction turns each fibre to its nearest guide's way out; Direction + Length also takes Guide Length to its length;
Shape gives each fibre its nearest guide's form at its own length times Guide Length; Range grows fur only within
Guide Range of a guide, at the guides' own length times Guide Length; Clump gathers the fibres within Guide Range to
the guides as Clumps gathers them to tufts, and makes no other tufts. The native grower grows the same as fur.py."""
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
ROOTS = [(.2, .2), (.8, .2), (.5, .5), (.2, .8), (.8, .8)]


def leaning(length=.3):
    """Straight guides leaning 45 degrees toward +X."""
    return [[(x + length * j / 6 * math.sqrt(.5), length * j / 6 * math.sqrt(.5), z) for j in range(7)] for x, z in ROOTS]


def bending(length=.3):
    """Guides rising, then over toward +X (a quarter circle)."""
    radius = length / (math.pi / 2)
    return [[(x + radius * (1 - math.cos(a)), radius * math.sin(a), z) for a in (math.pi / 2 * j / 6 for j in range(7))] for x, z in ROOTS]


def grown(mode, guides, **more):
    return fur.grow(FLOOR, dict(STILL, guides=mode, **more), None, guides)


class GuideModes(unittest.TestCase):
    def test_direction_turns_fibres_and_keeps_their_length(self):
        strands = grown('normal', leaning())[0]
        for strand in strands[:50]:
            way = [strand[-1][k] - strand[0][k] for k in range(3)]
            self.assertAlmostEqual(math.sqrt(sum(v * v for v in way)), .1, places=6)
            self.assertAlmostEqual(way[0], way[1], places=6)

    def test_direction_and_length_takes_guide_length(self):
        strands = grown('dirlen', leaning(), guideLength=.5)[0]
        way = [strands[0][-1][k] - strands[0][0][k] for k in range(3)]
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in way)), .05, places=6)

    def test_shape_takes_the_guides_form_at_the_fibres_length(self):
        strands = grown('shape', bending())[0]
        for strand in strands[:50]:
            along = sum(math.dist(a, b) for a, b in zip(strand, strand[1:]))
            self.assertLess(abs(along - .1), .002)
            self.assertGreater(strand[-1][0] - strand[0][0], .05)

    def test_range_grows_only_near_guides_at_their_own_length(self):
        strands = grown('range', leaning(), guideRange=.1)[0]
        self.assertTrue(strands)
        for strand in strands:
            self.assertLessEqual(min(math.dist((strand[0][0], strand[0][2]), r) for r in ROOTS), .1 + 1e-9)
            self.assertAlmostEqual(strand[-1][1] - strand[0][1], .3 * math.sqrt(.5), places=6)

    def test_clump_gathers_only_near_guides(self):
        plain = grown('none', leaning(), clumps=.8)[0]
        gathered = grown('clump', leaning(), clumps=.8, guideRange=.1)[0]
        self.assertEqual(len(plain), len(gathered))
        moved = [g for p, g in zip(grown('none', leaning())[0], gathered) if math.dist(p[-1], g[-1]) > 1e-9]
        self.assertTrue(moved)
        for strand in moved:
            self.assertLessEqual(min(math.dist((strand[0][0], strand[0][2]), r) for r in ROOTS), .1 + 1e-9)

    def test_no_guides_grows_as_before(self):
        self.assertEqual(grown('shape', [])[0], grown('none', [])[0])


@unittest.skipUnless(BUILT.is_file(), 'modo_fur_grow.exe has not been built (tools/build_fur_grower.py)')
class NativeGuides(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp())
        self.was = fur_native.program, fur_native.folder
        fur_native.program = lambda runtime=None: BUILT
        fur_native.folder = lambda: self.home

    def tearDown(self):
        fur_native.program, fur_native.folder = self.was
        shutil.rmtree(str(self.home), ignore_errors=True)

    def test_the_same_guided_fur_grows_as_in_python(self):
        for mode, guides, more in (('normal', leaning(), {}), ('dirlen', leaning(), {'guideLength': .5}), ('shape', bending(), {}),
                                   ('range', leaning(), {'guideRange': .15}), ('clump', leaning(), {'clumps': .8, 'guideRange': .1})):
            with self.subTest(mode=mode):
                held = dict(fur.CHANNELS, **dict(STILL, guides=mode, kinkAmp=.2, **more))
                strands = fur.grow(FLOOR, held, None, guides)[0]
                made = fur_native.grow(FLOOR, held, None, [0, 0], 0, None, guides)
                self.assertIsNotNone(made)
                vertices, counts, _, _, fibres = fur_native.read(made['files'][0][0])
                self.assertEqual((fibres, counts), (len(strands), [len(s) for s in strands]))
                flat = [p for s in strands for p in s]
                self.assertLess(max(abs(a - b) for p, q in zip(flat, vertices) for a, b in zip(p, q)), 1e-6)


if __name__ == '__main__':
    unittest.main()
