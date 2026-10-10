"""Hair grown from guides: roots on the scalp, the same every time, in clusters or between guides."""
import math
import sys
import types
import unittest
from pathlib import Path

for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import hair


def dome(radius=1.0, rings=12, around=24):
    """The upper half of a ball, as triangles."""
    def at(i, j):
        a, b = .5 * math.pi * i / rings, 2 * math.pi * j / around
        return (radius * math.sin(a) * math.cos(b), radius * math.cos(a), radius * math.sin(a) * math.sin(b))
    triangles = []
    for i in range(rings):
        for j in range(around):
            p, q, r, s = at(i, j), at(i, j + 1), at(i + 1, j + 1), at(i + 1, j)
            triangles += [(p, q, r), (p, r, s)]
    return triangles


def guides(count=12, radius=1.0, length=.5, points=6):
    found = []
    for index in range(count):
        a, b = .2 + .9 * (index % 4) / 4.0, 2 * math.pi * index / count
        normal = (math.sin(a) * math.cos(b), math.cos(a), math.sin(a) * math.sin(b))
        found.append([tuple(n * (radius + length * j / (points - 1)) for n in normal) for j in range(points)])
    return found


class Hair(unittest.TestCase):
    def test_nearest_point_on_the_scalp(self):
        scalp = hair.Scalp(dome())
        point, normal = scalp.nearest((0.0, 1.3, 0.0), 1.0)
        self.assertAlmostEqual(point[1], 1.0, delta=.02)
        self.assertGreater(abs(normal[1]), .9)
        self.assertIsNone(scalp.nearest((0.0, 9.0, 0.0), .5))

    def test_cluster_roots_lie_on_the_scalp(self):
        scalp = hair.Scalp(dome())
        strands, adrift = hair.grow(guides(), scalp, hair.CLUSTERS, count=25, width=.08, clump=.5, length_variation=.2, seed=3)
        self.assertEqual(len(strands), 12 * 25)
        self.assertEqual(adrift, 0)
        for strand in strands:
            # On the faceted dome a point of the surface is within a facet's sag of the true ball.
            self.assertAlmostEqual(math.sqrt(sum(v * v for v in strand[0])), 1.0, delta=.012)
            self.assertEqual(len(strand), 6)

    def test_the_same_hair_grows_every_time_and_a_seed_changes_it(self):
        scalp = hair.Scalp(dome())
        first = hair.grow(guides(), scalp, hair.CLUSTERS, count=5, width=.05, seed=7)[0]
        again = hair.grow(guides(), scalp, hair.CLUSTERS, count=5, width=.05, seed=7)[0]
        other = hair.grow(guides(), scalp, hair.CLUSTERS, count=5, width=.05, seed=8)[0]
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)

    def test_clump_closes_a_cluster_toward_its_guide(self):
        scalp = hair.Scalp(dome())
        one = guides(1)

        def spread(clump):
            strands = hair.grow(one, scalp, hair.CLUSTERS, count=40, width=.1, clump=clump, length_variation=0.0, seed=2)[0]
            tip = one[0][-1]
            return sum(math.sqrt(sum((a - b) ** 2 for a, b in zip(strand[-1], tip))) for strand in strands) / len(strands)
        self.assertLess(spread(1.0), .25 * spread(0.0))

    def test_between_guides_fills_the_space_and_stays_on_the_scalp(self):
        scalp = hair.Scalp(dome())
        made = guides(12)
        strands, adrift = hair.grow(made, scalp, hair.BETWEEN, count=30, width=.05, seed=4)
        self.assertEqual(len(strands), 12 * 30)
        self.assertEqual(adrift, 0)
        roots = [guide[0] for guide in made]
        # Roots are spread between the guides, not gathered at them.
        away = [min(math.sqrt(sum((a - b) ** 2 for a, b in zip(strand[0], root))) for root in roots) for strand in strands]
        self.assertGreater(sum(d > .05 for d in away), len(strands) // 3)
        for strand in strands:
            self.assertAlmostEqual(math.sqrt(sum(v * v for v in strand[0])), 1.0, delta=.012)

    def test_a_root_with_no_scalp_in_reach_stays_on_its_guide(self):
        scalp = hair.Scalp(dome())
        far = [[(5.0, 5.0 + .1 * j, 5.0) for j in range(4)]]
        strands, adrift = hair.grow(far, scalp, hair.CLUSTERS, count=6, width=.05, seed=1)
        self.assertEqual(adrift, len(far))
        for strand in strands:
            self.assertEqual(tuple(strand[0]), (5.0, 5.0, 5.0))


if __name__ == '__main__':
    unittest.main()
