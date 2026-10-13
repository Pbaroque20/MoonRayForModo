import pathlib
import shutil
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import fur, fur_native

BUILT = ROOT / 'build/native-avx/bin/modo_fur_grow.exe'
FLOOR = [((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 1, 0), (0, 1, 0), (0, 1, 0)), ((0, 0, 0), (1, 0, 1), (0, 0, 1), (0, 1, 0), (0, 1, 0), (0, 1, 0))]


@unittest.skipUnless(BUILT.is_file(), 'modo_fur_grow.exe has not been built (tools/build_fur_grower.py)')
class NativeFur(unittest.TestCase):
    def setUp(self):
        self.home = pathlib.Path(tempfile.mkdtemp())
        self.was = fur_native.program, fur_native.folder
        fur_native.program = lambda runtime=None: BUILT
        fur_native.folder = lambda: self.home

    def tearDown(self):
        fur_native.program, fur_native.folder = self.was
        shutil.rmtree(str(self.home), ignore_errors=True)

    def grown(self, held, groups=(0, 0), most=0, maps=None):
        return fur_native.grow(FLOOR, dict(fur.CHANNELS, **held), maps, list(groups), most)

    def test_the_same_fur_grows_as_in_python(self):
        held = {'dist': .02, 'curls': .2, 'clumps': .4, 'clumpSize': .1, 'kinkAmp': .3, 'frizAmp': .2, 'strays': .1}
        strands, root, tip, asked, _ = fur.grow(FLOOR, held)
        made = self.grown(held)
        vertices, counts, radii, places, fibres = fur_native.read(made['files'][0][0])
        self.assertEqual((made['wanted'], fibres, counts), (asked, len(strands), [len(strand) for strand in strands]))
        self.assertAlmostEqual(made['root'], root)
        flat = [point for strand in strands for point in strand]
        self.assertLess(max(abs(a - b) for p, q in zip(flat, vertices) for a, b in zip(p, q)), 1e-6)
        self.assertAlmostEqual(radii[0], root, places=6)
        self.assertAlmostEqual(places[len(strands[0]) - 1][1], 1.0, places=5)

    def test_every_fibre_modo_would_grow_is_grown_no_wider(self):
        made = self.grown({'dist': .002})
        self.assertEqual((made['wanted'], made['grown']), (250000, 250000))
        self.assertAlmostEqual(made['root'], .002 * .5 / 2)

    def test_each_material_has_a_file_of_its_own(self):
        made = self.grown({'dist': .02}, groups=(0, 1))
        self.assertEqual(sorted(made['files']), [0, 1])
        self.assertEqual(sum(fibres for _, fibres, _ in made['files'].values()), made['grown'])

    def test_a_share_of_a_file_can_be_read(self):
        made = self.grown({'dist': .01})
        _, counts, _, _, fibres = fur_native.read(made['files'][0][0], most=1000)
        self.assertEqual(fibres, 10000)
        self.assertLessEqual(len(counts), 1000)
        self.assertGreater(len(counts), 900)

    def test_the_same_request_is_not_grown_twice(self):
        first = self.grown({'dist': .02})
        stamp = first['files'][0][0].stat().st_mtime_ns
        second = self.grown({'dist': .02})
        self.assertEqual(second['files'][0][0].stat().st_mtime_ns, stamp)


if __name__ == '__main__':
    unittest.main()
