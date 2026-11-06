"""Curves by the geometry adapter (native-modo/curves.cpp): a batch's radii and UVs (extra_geometry.batches) and
MoonLightIPR's segments of a curve geometry (moonlightipr_curves.payload), against the Python that worked them out
before: lines, Beziers and B-splines, strands too short, radii by point, by strand and one, UVs by strand and by point,
with and without motion. MoonLightIPR's packing is the same bytes; a batch's numbers are the same where this Python's
math.dist is Modo's (the exact check runs in Modo, tools/probe_cl_curves_native.py)."""
import math
import os
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / 'build/modo-bridge/MoonRayGeometry.lx'
os.environ.setdefault('MOONRAY_MODO_GEOMETRY', str(ADAPTER))
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import extra_geometry, moonlightipr_curves, rows  # noqa: E402


def strands(seed, count=60, sizes=(1, 2, 3, 4, 5, 7, 10, 13)):
    chance = random.Random(seed)
    made = []
    for s in range(count):
        n = chance.choice(sizes)
        x, y = chance.uniform(-1, 1), chance.uniform(-1, 1)
        made.append([[x + .01 * k, y + chance.uniform(-.02, .02), .1 * k * chance.uniform(.5, 1.5)] for k in range(n)])
    return made


@unittest.skipUnless(ADAPTER.is_file(), 'the geometry adapter is not built (tools/build_modo_bridge.py)')
class Batches(unittest.TestCase):
    def setUp(self):
        if rows._native() is None or not hasattr(rows._native(), 'MR_curve_shape'):
            self.skipTest('the adapter has no MR_curve_shape')

    def made(self, native, given, shape, material=''):
        held = extra_geometry._shaped_natively
        if not native:
            extra_geometry._shaped_natively = lambda *a: None
        try:
            return extra_geometry.batches('id', 'Hair', given, shape, material, [1.0] * 16)
        finally:
            extra_geometry._shaped_natively = held

    def test_tapers_uvs_and_scales(self):
        given = [(strand, 'm%d' % (i % 3), None) for i, strand in enumerate(strands(1))]
        for shape in ({'root': .01, 'tip': .002, 'envelope': 1.0, 'uv': True},
                      {'root': .01, 'tip': .002, 'envelope': 2.5, 'uv': False},
                      {'root': .01, 'tip': .01, 'envelope': 1.0, 'uv': True},
                      {'root': .01, 'tip': .01, 'envelope': .5, 'uv': True, 'scales': [1 + .01 * i for i in range(len(given))]}):
            for material in ('', 'one'):
                native, python = self.made(True, given, shape, material), self.made(False, given, shape, material)
                with self.subTest(shape=shape, material=material):
                    self.assertEqual(len(native), len(python))
                    for a, b in zip(native, python):
                        self.assertEqual(a['vertices'], b['vertices'])
                        self.assertEqual(a['counts'], b['counts'])
                        self.assertEqual('radii' in a, 'radii' in b)
                        self.assertEqual('uvs' in a, 'uvs' in b)
                        for x, y in zip(a.get('radii', []), b.get('radii', [])):
                            self.assertAlmostEqual(x, y, delta=1e-15)
                        for x, y in zip(a.get('uvs', []), b.get('uvs', [])):
                            self.assertAlmostEqual(x[0], y[0], delta=0)
                            self.assertAlmostEqual(x[1], y[1], delta=1e-15)


@unittest.skipUnless(ADAPTER.is_file(), 'the geometry adapter is not built (tools/build_modo_bridge.py)')
class Segments(unittest.TestCase):
    def setUp(self):
        if rows._native() is None or not hasattr(rows._native(), 'MR_curve_segments'):
            self.skipTest('the adapter has no MR_curve_segments')

    def packed(self, entry, slot, native):
        moonlightipr_curves.BUILT.clear()
        moonlightipr_curves.SAME.clear()
        held = moonlightipr_curves.built_natively
        if not native:
            moonlightipr_curves.built_natively = lambda *a: None
        try:
            return moonlightipr_curves.payload(entry, slot)
        finally:
            moonlightipr_curves.built_natively = held

    def test_every_kind_radius_and_uv(self):
        for kind, sizes in ((0, (1, 2, 3, 5)), (1, (1, 4, 7, 10)), (2, (1, 4, 5, 9)), (1, (2, 4, 5)), (2, (2, 3, 6))):
            made = strands(kind + 10 * len(sizes), 40, sizes)
            vertices = [p for s in made for p in s]
            counts = [len(s) for s in made]
            chance = random.Random(kind)
            for radii in (None, [chance.uniform(-.001, .01) for _ in vertices], [chance.uniform(0, .01) for _ in counts]):
                for uvs, slot in ((None, None), ([[chance.random(), chance.random()] for _ in counts], 2),
                                  ([[chance.random(), chance.random()] for _ in vertices], 1)):
                    for closing in (None, [[x + .1, y, z] for x, y, z in vertices]):
                        entry = {'name': 'C', 'vertices': vertices, 'counts': counts, 'curve_type': kind, 'radius': .003}
                        if radii is not None:
                            entry['radii'] = radii
                        if uvs is not None:
                            entry['uvs'] = uvs
                        if closing is not None:
                            entry['vertices_close'] = closing
                        with self.subTest(kind=kind, sizes=sizes, radii=radii is not None and len(radii), uvs=uvs is not None and len(uvs), closing=closing is not None):
                            self.assertEqual(self.packed(entry, slot, True), self.packed(entry, slot, False))

    def test_nothing_to_draw(self):
        entry = {'name': 'C', 'vertices': [[0, 0, 0], [1, 0, 0]], 'counts': [1, 1]}
        self.assertIsNone(self.packed(entry, None, True))
        self.assertIsNone(self.packed(entry, None, False))



class GrownStrands(unittest.TestCase):
    """The hair grower's answer kept as one run (hair_native.Strand), read as lists of points, and batched from it."""

    def answer(self, made):
        import struct
        from array import array
        flat = array('d', (v for s in made for p in s for v in p))
        return struct.pack('<4s2q', b'MHS1', 2, len(made)) + array('i', map(len, made)).tobytes() + flat.tobytes()

    def test_read_as_lists(self):
        from moonray_modo import hair_native
        made = strands(5, 20, (2, 3, 9))
        got, adrift = hair_native.answer(self.answer(made))
        self.assertEqual(adrift, 2)
        self.assertEqual([list(s) for s in got], made)
        self.assertEqual(got[3][1], made[3][1])
        self.assertEqual(got[3][-1], made[3][-1])
        self.assertEqual(got[3][1:], made[3][1:])
        self.assertEqual(len(got[3]), len(made[3]))
        held = [[0.0, 0.0, 0.0]]
        same = held
        held += got[0]
        self.assertIs(held, same)
        self.assertEqual(held, [[0.0, 0.0, 0.0]] + made[0])

    @unittest.skipUnless(ADAPTER.is_file(), 'the geometry adapter is not built')
    def test_batched_as_lists_are(self):
        from moonray_modo import hair_native
        made = strands(6, 30, (2, 4, 16))
        got, _ = hair_native.answer(self.answer(made))
        shape = {'root': .01, 'tip': .001, 'envelope': 1.3, 'uv': True}
        guides = [(s, 'g', None) for s in strands(7, 3, (5,))]
        flat = extra_geometry.batches('id', 'H', guides + [(s, 'm', None) for s in got], shape, '', [1.0] * 16)
        lists = extra_geometry.batches('id', 'H', guides + [(s, 'm', None) for s in made], shape, '', [1.0] * 16)
        for a, b in zip(flat, lists):
            self.assertEqual(a['vertices'], b['vertices'])
            self.assertEqual(a['radii'], b['radii'])
            self.assertEqual(list(a['uvs']), list(b['uvs']))
        held = extra_geometry._shaped_natively
        extra_geometry._shaped_natively = lambda *a: None
        try:
            python = extra_geometry.batches('id', 'H', [(s, 'm', None) for s in got], shape, '', [1.0] * 16)
        finally:
            extra_geometry._shaped_natively = held
        self.assertEqual(python[0]['vertices'], made_points(made))


def made_points(made):
    return [p for s in made for p in s]


if __name__ == '__main__':
    unittest.main()
