"""Modo's Fur material, grown as curves: as many fibres as the material's spacing asks, as long, as wide, and leaning."""
import math
import sys
import types
import unittest
from pathlib import Path

for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import fur

UP = (0.0, 1.0, 0.0)
# A square metre of floor, facing up.
FLOOR = [((0, 0, 0), (0, 0, 1), (1, 0, 1), UP, UP, UP), ((0, 0, 0), (1, 0, 1), (1, 0, 0), UP, UP, UP)]


def held(**changed):
    return dict(fur.CHANNELS, **changed)


class Fur(unittest.TestCase):
    def test_as_many_fibres_as_the_spacing_asks_stand_on_the_surface(self):
        strands, root, tip, asked, stands = fur.grow(FLOOR, held(dist=.02))
        self.assertEqual(len(stands), len(strands))
        self.assertEqual(set(stands), {0, 1})
        self.assertEqual((asked, len(strands)), (2500, 2500))
        for strand in strands:
            x, y, z = strand[0]
            self.assertTrue(0 <= x <= 1 and 0 <= z <= 1 and abs(y) < 1e-12)
        # Relative width is a share of the spacing, and the fibre tapers to a fine tip.
        self.assertAlmostEqual(root, .02 * .5 / 2)
        self.assertLess(tip, root * .1)

    def test_a_fibre_is_as_long_as_the_material_says_and_leans_down(self):
        strands = fur.grow(FLOOR, held(dist=.05, length=.1, sclJitter=0.0, growthJitter=0.0, nrmJitter=0.0, flex=0.0))[0]
        for strand in strands[:20]:
            self.assertAlmostEqual(strand[-1][1] - strand[0][1], .1, places=9)
        # A wall facing +x: with flex its fibres droop below where they started out to.
        east = (1.0, 0.0, 0.0)
        wall = [((0, 0, 0), (0, 1, 0), (0, 1, 1), east, east, east)]
        stiff = fur.grow(wall, held(dist=.05, nrmJitter=0.0, flex=0.0))[0]
        limp = fur.grow(wall, held(dist=.05, nrmJitter=0.0, flex=1.0))[0]
        self.assertTrue(all(abs(s[-1][1] - s[0][1]) < 1e-9 for s in stiff))
        self.assertTrue(all(s[-1][1] < s[0][1] - .005 for s in limp))

    def test_too_many_fibres_are_grown_fewer_and_wider(self):
        strands, root, _, asked, _ = fur.grow(FLOOR, held(dist=.002))
        self.assertEqual((asked, len(strands)), (250000, fur.MOST))
        self.assertAlmostEqual(root, .002 * math.sqrt(250000 / fur.MOST) * .5 / 2)

    def test_the_same_fur_grows_each_time_and_is_kept(self):
        first = fur.kept(FLOOR, held(dist=.05))
        self.assertIs(fur.kept(FLOOR, held(dist=.05)), first)
        self.assertEqual(fur.grow(FLOOR, held(dist=.05))[0], first[0])
        self.assertNotEqual(fur.grow(FLOOR, held(dist=.05, seed=7))[0], first[0])

    def test_what_modo_leaves_to_follow_is_taken_at_its_start_and_what_is_not_read_is_named(self):
        values = {'taper': -666.0, 'length': .2, 'curls': .5, 'guides': 'none', 'densityMap': 'Weight'}
        def read(key):
            return values[key]
        got = fur.settings(read)
        self.assertEqual((got['taper'], got['length'], got['dist']), (1.0, .2, .005))
        self.assertEqual(fur.unread(read), ['curls', 'its maps'])


if __name__ == '__main__':
    unittest.main()
