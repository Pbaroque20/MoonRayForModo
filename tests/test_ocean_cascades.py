"""The ocean over cascades (ocean.CASCADES, the Ocean node's Cascades, on by default): three tiles of unrelated sizes
(golden-ratio powers), the one tile's waves shared out between them by length, scaled together to a fully developed
sea's heights, so that the sea's pattern never repeats in sight. Added for the displacement, screened for the foam;
MoonRay's split on the finest; MoonLightIPR's slopes added."""
import math
import os
import pathlib
import statistics
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
for _name in ('lx', 'lxu', 'lxifc', 'modo'):
    sys.modules.setdefault(_name, types.ModuleType(_name))
from moonray_modo import nodes, ocean  # noqa: E402


def graph(**params):
    g = nodes.new('DwaBaseMaterial', {'albedo': [0.02, 0.05, 0.08], 'roughness': 0.05})
    g['nodes']['sea'] = {'type': 'ocean', 'parameters': dict({'resolution': 64}, **params), 'inputs': {}, 'position': [0, 0]}
    g['nodes']['push'] = {'type': 'VectorDisplacement', 'parameters': {}, 'inputs': {'vector': 'sea'}, 'position': [0, 0]}
    g['displacement'] = 'push'
    g['nodes']['foam'] = {'type': 'ocean_foam', 'parameters': {}, 'inputs': {}, 'position': [0, 0]}
    g['nodes']['surface']['inputs']['albedo'] = 'foam'
    return g


class Cascades(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.patch = mock.patch('moonray_modo.ocean.folder', return_value=pathlib.Path(self.folder.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.folder.cleanup()

    def test_three_tiles_of_unrelated_sizes_sharing_the_waves(self):
        parts = ocean.cascade_values(ocean.settings({'resolution': 64}))
        self.assertEqual(len(parts), 4)
        sizes = [p['size'] for p in parts]
        self.assertAlmostEqual(sizes[2], ocean.FITTED_SIZE)
        # No two repeat together: their ratios are irrational (golden-ratio powers), not near a small fraction.
        for a in range(4):
            for b in range(a + 1, 4):
                ratio = sizes[a] / sizes[b]
                self.assertGreater(min(abs(ratio * q - round(ratio * q)) for q in range(1, 9)), 0.02)
        # The bands meet, from the one tile's longest wave (one cycle across it) with no end.
        self.assertAlmostEqual(parts[0]['k_low'], 2 * math.pi / ocean.FITTED_SIZE)
        self.assertAlmostEqual(parts[0]['k_high'], parts[1]['k_low'])
        self.assertAlmostEqual(parts[1]['k_high'], parts[2]['k_low'])
        self.assertAlmostEqual(parts[2]['k_high'], parts[3]['k_low'])
        self.assertEqual(parts[3]['k_high'], 0.0)
        self.assertEqual(len({p['seed'] for p in parts}), 4)
        # Each tile holds five or more of its own longest waves.
        for p in parts:
            self.assertGreaterEqual(p['k_low'] * p['size'] / (2 * math.pi), 4.2)
        self.assertEqual(len({p['fixed_scale'] for p in parts}), 1)
        self.assertEqual(ocean.cascade_values(ocean.settings({'cascades': False})), [ocean.settings({'cascades': False})])

    def test_together_the_heights_are_a_fully_developed_seas(self):
        value = ocean.settings({'resolution': 128, 'wind_speed': 10})
        variance = 0.0
        for part in ocean.cascade_values(value):
            heights = [d[1] for d in ocean.fields(part, 1.0)[0]]
            variance += statistics.pvariance(heights)
        target = 0.21 * 100 / 9.81 / 4
        self.assertAlmostEqual(math.sqrt(variance), target, delta=target * 0.25)

    def test_the_native_library_makes_a_cascade_as_python_does(self):
        if ocean.library() is None:
            self.skipTest('modo_ocean.dll not built')
        part = ocean.cascade_values(ocean.settings({'resolution': 64}))[2]
        native = ocean.paths(part, 0.5)
        self.assertTrue(ocean.native_tile(part, 0.5, *native))
        held = native[0].read_bytes()
        with mock.patch('moonray_modo.ocean.library', return_value=None):
            vectors, _, _ = ocean.fields(part, 0.5, slopes=True)
            ocean.write_pfm(pathlib.Path(self.folder.name) / 'python.pfm', 64, vectors, 3)
        mine = (pathlib.Path(self.folder.name) / 'python.pfm').read_bytes()
        self.assertEqual(len(held), len(mine))
        import struct
        start = len(held) - 64 * 64 * 12
        a = struct.unpack('<%df' % (64 * 64 * 3), held[start:])
        b = struct.unpack('<%df' % (64 * 64 * 3), mine[start:])
        self.assertLess(max(abs(x - y) for x, y in zip(a, b)), 1e-4)

    def test_the_graph_adds_the_displacements_and_screens_the_foams(self):
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(2.0):
            g = nodes.validate(graph(repeat=[4, 4]))
        members = g['nodes']
        sea = members['sea']
        self.assertEqual(sea['type'], 'add')
        tiles = sorted((k for k in members if k.startswith('sea__cascade')))
        self.assertEqual(len(tiles), 4)
        scales = [members[k]['parameters']['scale'][0] for k in tiles]
        for scale, (ratio, _, _) in zip(scales, ocean.CASCADES):
            self.assertAlmostEqual(scale, 4.0 / ratio)
        self.assertTrue(all(members[k].get('_slope') for k in tiles))
        self.assertEqual(members['foam']['type'], 'mix')
        self.assertEqual(members['foam']['parameters']['fg'], [1.0, 1.0, 1.0])

    def test_moonray_splits_the_finest_cascade(self):
        g = graph(repeat=[4, 4])
        g['nodes']['sea']['_spacing'] = 0.05
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(2.0):
            v = nodes.expand_ocean(nodes.effective(g))
            split = [k for k, n in v['nodes'].items() if n.get('_split')]
            self.assertEqual(split, [k for k in v['nodes'] if k.startswith('sea__cascade3')])
            nodes.split_ocean(v, 'surface')
        self.assertTrue(any(k.endswith('__long') for k in v['nodes']))
        self.assertIn('input_normal', v['nodes']['surface']['inputs'])

    def test_moonlightipr_adds_each_cascades_slope(self):
        from moonray_modo import moonlightipr_materials
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(2.0):
            found = moonlightipr_materials.displacement_tree({'node_graph': graph(repeat=[4, 4])}, lambda what: None)
        leaves, program = found
        slopes = [layer for _, _, layers in leaves for layer in layers if layer.get('effect') == '_slope']
        self.assertEqual(len(slopes), 4)
        self.assertEqual([s['blend'] for s in slopes], ['normal', 'add', 'add', 'add'])
        self.assertEqual([s.get('rotation') for s in slopes], list(ocean.TURNS))


    def test_a_turned_cascade_looked_up_as_moonray_turns_it_matches_its_slope_and_push(self):
        # MoonRay's ImageMap turns its coordinates by rotation_angle (about 0 here) before scaling: tile = (u c + v s,
        # -u s + v c). Looked up so, the heights must rise the way the stored slope says, and the pushes run against
        # that rise, as an unturned tile's do: the slope and push are written in the surface's frame.
        with mock.patch('moonray_modo.ocean.library', return_value=None):
            part = ocean.cascade_values(ocean.settings({'resolution': 64, 'choppiness': 1.0}))[2]
            vectors, _, slopes = ocean.fields(part, 0.7, slopes=True)
            flat, _, flat_slopes = ocean.fields(dict(part, choppiness=0.0), 0.7, slopes=True)
        n, turn = 64, math.radians(part['turn'])
        c, s = math.cos(turn), math.sin(turn)

        def sample(grid, u, v, k):
            # The tile at surface (u, v), bilinear, periodic, one tile a unit; rows by z (v), columns by x (u).
            tu, tv = (u * c + v * s) * n, (-u * s + v * c) * n
            i0, j0 = math.floor(tu), math.floor(tv)
            fu, fv = tu - i0, tv - j0

            def at(i, j):
                return grid[(j % n) * n + (i % n)][k]
            return ((1 - fu) * (1 - fv) * at(i0, j0) + fu * (1 - fv) * at(i0 + 1, j0) + (1 - fu) * fv * at(i0, j0 + 1)
                    + fu * fv * at(i0 + 1, j0 + 1))
        eps = 0.25 / n
        agree = against = total = 0.0
        for a in range(40):
            for b in range(40):
                u, v = (a + .37) / 40, (b + .61) / 40
                gx = (sample(flat, u + eps, v, 1) - sample(flat, u - eps, v, 1)) / (2 * eps)
                gz = (sample(flat, u, v + eps, 1) - sample(flat, u, v - eps, 1)) / (2 * eps)
                sx, sz = sample(flat_slopes, u, v, 0), sample(flat_slopes, u, v, 1)
                agree += gx * sx + gz * sz
                total += math.hypot(gx, gz) * math.hypot(sx, sz)
                against += -(gx * sample(vectors, u, v, 0) + gz * sample(vectors, u, v, 2))
        self.assertGreater(agree / total, 0.9)
        self.assertGreater(against, 0.0)


if __name__ == '__main__':
    unittest.main()
