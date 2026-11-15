"""The ocean's swell (the Ocean node's Swell Height, Length and Direction): one long, regular wave through the sea, on a
tile of its own one wave long, turned to its direction and added to the wind's tiles. It must be the wave the FFT
tiles would make of the same single wave (so that it runs and sharpens as the wind's waves do), leave the wind's tiles
as they were, travel at a real swell's speed, and reach every engine as one more added tile."""
import math
import os
import pathlib
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


class Swell(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.patch = mock.patch('moonray_modo.ocean.folder', return_value=pathlib.Path(self.folder.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.folder.cleanup()

    def test_none_by_default(self):
        value = ocean.settings({})
        self.assertEqual(value['swell_height'], 0.0)
        self.assertEqual(ocean.swell_values(value), [])

    def test_a_tile_one_wave_long_turned_to_its_direction(self):
        parts = ocean.swell_values(ocean.settings({'swell_height': 2.0, 'swell_length': 150.0, 'swell_direction': 30.0}))
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0]['size'], 150.0)
        self.assertEqual(parts[0]['turn'], 30.0)
        self.assertTrue(parts[0]['swell'])

    def test_settings_checked(self):
        with self.assertRaises(ValueError):
            ocean.settings({'swell_length': 0.0})
        with self.assertRaises(ValueError):
            ocean.settings({'swell_height': -1.0})

    def test_the_same_wave_the_fft_makes_of_it(self):
        # One wave on the FFT's tile (fields): h0 at +1 cycle along x only, A / 2 for a wave of amplitude A (its
        # mirror cell adds the other half), so the height is A cos(k x + w t), A half the height from trough to crest.
        # The swell's own fields must match it point for point: height, push and slope, turned and not.
        n, size, height, time = 64, 100.0, 3.0, 1.7
        for turn in (0.0, 35.0):
            value = dict(ocean.settings({'resolution': n, 'choppiness': 0.8, 'swell_height': height, 'swell_length': size}),
                         size=size, turn=turn, swell=True)
            h0 = [[0j] * n for _ in range(n)]
            h0[n // 2][n // 2 + 1] = complex(height / 4.0, 0.0)
            with mock.patch('moonray_modo.ocean.initial', return_value=(h0, 1.0)):
                vectors, _, slopes = ocean.fields(value, time, slopes=True)
            mine, foam, mine_slopes = ocean.swell_fields(value, time)
            self.assertEqual(len(mine), n * n)
            self.assertEqual(max(foam), 0.0)
            for a, b in zip(vectors, mine):
                for x, y in zip(a, b):
                    self.assertAlmostEqual(x, y, places=6)
            for a, b in zip(slopes, mine_slopes):
                for x, y in zip(a, b):
                    self.assertAlmostEqual(x, y, places=5)

    def test_runs_at_a_swells_speed(self):
        # Deep water: a 120 m swell's crests travel at sqrt(g L / 2 pi), about 13.7 m/s.
        value = ocean.swell_values(ocean.settings({'swell_height': 2.0, 'swell_length': 120.0, 'choppiness': 0.0}))[0]
        k = 2 * math.pi / 120.0
        self.assertAlmostEqual(ocean.swell_frequency(value, k) / k, math.sqrt(9.81 * 120.0 / (2 * math.pi)), places=6)

    def test_a_loop_keeps_a_long_swell_moving(self):
        value = ocean.swell_values(ocean.settings({'swell_height': 2.0, 'swell_length': 400.0, 'loop': 5.0}))[0]
        w = ocean.swell_frequency(value, 2 * math.pi / 400.0)
        self.assertGreater(w, 0.0)
        self.assertAlmostEqual(w * 5.0 / (2 * math.pi), round(w * 5.0 / (2 * math.pi)))

    def test_the_wind_tiles_keys_do_not_change(self):
        plain = ocean.cascade_values(ocean.settings({'resolution': 64}))
        swelled = ocean.cascade_values(ocean.settings({'resolution': 64, 'swell_height': 3.0}))
        self.assertEqual([ocean.key(p, 1.0) for p in plain], [ocean.key(p, 1.0) for p in swelled])
        one = ocean.swell_values(ocean.settings({'swell_height': 3.0}))[0]
        two = ocean.swell_values(ocean.settings({'swell_height': 3.5}))[0]
        self.assertNotEqual(ocean.key(one, 1.0), ocean.key(two, 1.0))
        self.assertNotEqual(ocean.key(one, 1.0), ocean.key(one, 1.5))

    def test_the_bound_padding_has_room_for_it(self):
        self.assertGreater(ocean.reach(ocean.settings({'swell_height': 4.0})), ocean.reach(ocean.settings({})) + 4.0)

    def test_the_graph_adds_its_tile_first_and_the_foam_has_none(self):
        g = graph(repeat=[4, 4], swell_height=2.0, swell_length=160.0, swell_direction=25.0)
        g['nodes']['sea']['_spacing'] = 0.05
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(2.0):
            v = nodes.expand_ocean(nodes.effective(g))
        members = v['nodes']
        tiles = sorted(k for k in members if k.startswith('sea__cascade') and members[k].get('type') == 'ImageMap')
        self.assertEqual(len(tiles), 5)
        swell = members['sea__cascade0']['parameters']
        self.assertAlmostEqual(swell['scale'][0], 4.0 * 80.0 / 160.0)
        self.assertEqual(swell['rotation_angle'], 25.0)
        self.assertTrue(pathlib.Path(swell['texture']).is_file())
        # MoonRay's split stays on the finest wind tile, last.
        self.assertEqual([k for k, n in members.items() if n.get('_split')], ['sea__cascade4'])
        foams = [k for k in members if k.startswith('foam__cascade') and members[k].get('type') == 'ImageMap']
        self.assertEqual(len(foams), 4)

    def test_moonlightipr_adds_its_slope(self):
        from moonray_modo import moonlightipr_materials
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(2.0):
            leaves, _ = moonlightipr_materials.displacement_tree(
                {'node_graph': graph(repeat=[4, 4], swell_height=2.0, swell_direction=25.0)}, lambda what: None)
        slopes = [layer for _, _, layers in leaves for layer in layers if layer.get('effect') == '_slope']
        self.assertEqual([s.get('rotation') for s in slopes], [25.0] + list(ocean.TURNS))

    def test_the_ocean_plane_exposes_it(self):
        from moonray_modo import ocean_plane
        for key in ocean.SWELL_KEYS:
            self.assertIn(key, ocean_plane.OCEAN_KEYS)
            self.assertIn(key, nodes.MAPS['ocean'])


if __name__ == '__main__':
    unittest.main()
