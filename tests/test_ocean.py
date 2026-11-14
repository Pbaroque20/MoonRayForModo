"""The ocean (ocean.py, nodes.expand_ocean): Tessendorf's FFT waves made by the kit for each frame, its heights a fully
developed sea's for the wind, the kit's modo_ocean.dll and the Python model alike, and the graph's Ocean nodes taken
by every engine as a VectorDisplacement and images of the tile, flat with the MoonRay Source Override off."""
import os
import pathlib
import statistics
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import nodes, ocean  # noqa: E402


def graph(**params):
    g = nodes.new('DwaBaseMaterial', {'albedo': [0.02, 0.05, 0.08], 'roughness': 0.05})
    g['nodes']['sea'] = {'type': 'ocean', 'parameters': dict({'resolution': 64}, **params), 'inputs': {}, 'position': [0, 0]}
    g['displacement'] = 'sea'
    return g


class Model(unittest.TestCase):
    def test_heights_are_a_fully_developed_seas(self):
        value = ocean.settings({'resolution': 64, 'wind_speed': 10})
        heights = [d[1] for d in ocean.fields(value, 1.0)[0]]
        # Pierson-Moskowitz: significant height 0.21 V^2 / g, four times the spread of the heights.
        self.assertAlmostEqual(statistics.pstdev(heights), 0.21 * 100 / 9.81 / 4, delta=0.1)
        self.assertAlmostEqual(statistics.fmean(heights), 0.0, delta=0.02)

    def test_the_waves_move_and_repeat_with_the_loop(self):
        value = ocean.settings({'resolution': 64, 'loop': 8.0})
        first, later, again = (ocean.fields(value, t)[0] for t in (0.0, 1.0, 8.0))
        self.assertNotEqual(first, later)
        for a, b in zip(first, again):
            for x, y in zip(a, b):
                self.assertAlmostEqual(x, y, places=4)

    def test_stronger_wind_choppier_waves_more_foam(self):
        calm = ocean.fields(ocean.settings({'resolution': 64, 'wind_speed': 6, 'choppiness': 0.5}), 1.0)[1]
        storm = ocean.fields(ocean.settings({'resolution': 64, 'wind_speed': 20, 'choppiness': 2}), 1.0)[1]
        self.assertLess(sum(calm), sum(storm))

    def test_settings_are_checked(self):
        for bad in ({'resolution': 100}, {'wind_speed': 0}, {'choppiness': -1}, {'depth': float('nan')}):
            with self.assertRaises(ValueError):
                ocean.settings(bad)

    def test_the_library_draws_the_same_sea(self):
        dll = ROOT / 'build/native-avx/bin/modo_ocean.dll'
        if ocean.library(dll) is None:
            self.skipTest('modo_ocean.dll not built (tools/build_ocean.py)')
        import array
        value = ocean.settings({'resolution': 64, 'choppiness': 1.5, 'wind_speed': 14, 'seed': 3})
        expected, foam = ocean.fields(value, 2.5)
        with tempfile.TemporaryDirectory() as folder:
            out = [pathlib.Path(folder) / 'd.pfm', pathlib.Path(folder) / 'f.pfm', pathlib.Path(folder) / 's.pfm']
            self.assertTrue(ocean.native_tile(value, 2.5, out[0], out[1], out[2], dll))
            slopes = array.array('f')
            slopes.frombytes(out[2].read_bytes().split(b'\n', 3)[3][:64 * 64 * 12])
            data = out[0].read_bytes().split(b'\n', 3)[3]
            got = array.array('f')
            got.frombytes(data[:64 * 64 * 12])
            mask = array.array('f')
            mask.frombytes(out[1].read_bytes().split(b'\n', 3)[3][:64 * 64 * 12])
        for a, b in zip((c for v in expected for c in v), got):
            self.assertAlmostEqual(a, b, places=4)
        # The foam a grey image of three channels.
        for a, b in zip((f for f in foam for _ in range(3)), mask):
            self.assertAlmostEqual(a, b, places=4)
        # The slope as the Python model works it out.
        for a, b in zip((c for v in ocean.fields(value, 2.5, slopes=True)[2] for c in v), slopes):
            self.assertAlmostEqual(a, b, delta=1e-3 * max(1.0, abs(a)))

    def test_the_slope_is_the_heights_change(self):
        # With no sideways push, the slope across one tile is the heights' change from point to point times the points.
        value = ocean.settings({'resolution': 64, 'choppiness': 0, 'small_waves': 3.0})  # long waves, which a difference follows
        heights, _, slopes = ocean.fields(value, 1.0, slopes=True)
        n = 64
        for j in range(0, n, 7):
            for i in range(0, n, 7):
                du = (heights[j * n + (i + 1) % n][1] - heights[j * n + (i - 1) % n][1]) / 2 * n
                dv = (heights[((j + 1) % n) * n + i][1] - heights[((j - 1) % n) * n + i][1]) / 2 * n
                self.assertAlmostEqual(slopes[j * n + i][0], du, delta=0.1 + 0.03 * abs(du))
                self.assertAlmostEqual(slopes[j * n + i][1], dv, delta=0.1 + 0.03 * abs(dv))

    def test_the_split_keeps_the_long_waves_and_shades_the_rest(self):
        # ocean split: below the cutoff the long waves' displacement is the tile's; well above it, flat; the normal map
        # is the slope the long waves leave out, flat where there is none.
        value = ocean.settings({'resolution': 64, 'choppiness': 0, 'small_waves': 0.0})
        full, _, slopes = ocean.fields(value, 1.0, slopes=True)
        long_waves, _, long_slopes = ocean.fields(value, 1.0, slopes=True, cutoff=4.0)
        spread = lambda field: statistics.pstdev(v[1] for v in field)
        self.assertLess(spread(long_waves), spread(full))
        self.assertGreater(spread(long_waves), 0.2 * spread(full))
        normals = ocean.fine_normals(slopes, long_slopes, value['size'])
        self.assertTrue(all(0.0 <= c <= 1.0 for n in normals for c in n))
        self.assertTrue(any(abs(n[0] - 0.5) > 1e-3 for n in normals))
        self.assertEqual(ocean.fine_normals(slopes, slopes, value['size'])[0], (0.5, 0.5, 1.0))
        # The cutoff: four dicing steps to a wave, a power of two, none where the dicing follows every wave.
        self.assertEqual(ocean.cutoff(1 / 128.0, 1024), 32.0)
        self.assertEqual(ocean.cutoff(1 / 100.0, 1024), 32.0)
        self.assertIsNone(ocean.cutoff(1 / 4096.0, 1024))
        self.assertIsNone(ocean.cutoff(0.0, 1024))

    def test_the_library_splits_as_python_does(self):
        dll = ROOT / 'build/native-avx/bin/modo_ocean.dll'
        if ocean.library(dll) is None or not hasattr(ocean.library(dll), 'modo_ocean_tile_split'):
            self.skipTest('modo_ocean.dll with the split not built (tools/build_ocean.py)')
        import array
        value = ocean.settings({'resolution': 64, 'choppiness': 1.2, 'wind_speed': 12, 'seed': 5})
        _, _, full = ocean.fields(value, 1.5, slopes=True)
        long_waves, _, long_slopes = ocean.fields(value, 1.5, slopes=True, cutoff=8.0)
        expected = ocean.fine_normals(full, long_slopes, value['size'])
        with tempfile.TemporaryDirectory() as folder, mock.patch('moonray_modo.ocean.library', return_value=ocean.library(dll)):
            made = [pathlib.Path(folder) / name for name in ('d.pfm', 'f.pfm', 's.pfm')]
            split = [pathlib.Path(folder) / 'c.pfm', pathlib.Path(folder) / 'n.pfm']
            self.assertTrue(ocean.native_split(value, 1.5, 8.0, made, split))
            read = lambda p: array.array('f', p.read_bytes().split(b'\n', 3)[3][:64 * 64 * 12])
            coarse, fine = read(split[0]), read(split[1])
        for a, b in zip((c for v in long_waves for c in v), coarse):
            self.assertAlmostEqual(a, b, places=4)
        for a, b in zip((c for v in expected for c in v), fine):
            self.assertAlmostEqual(a, b, delta=2e-3)


class Nodes(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.patch = mock.patch('moonray_modo.ocean.folder', return_value=pathlib.Path(self.folder.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.folder.cleanup()

    def test_an_ocean_is_a_vector_displacement_of_its_tile(self):
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(2.0):
            g = nodes.validate(graph(repeat=[4, 4]))
        sea = g['nodes'][g['displacement']]
        self.assertEqual(sea['type'], 'VectorDisplacement')
        self.assertEqual(sea['parameters']['source_space'], 0)
        tile = g['nodes'][sea['inputs']['vector']]
        # MoonRay's own ImageMap, read as it is: the kit's image node divided by an alpha these images have not.
        self.assertEqual(tile['type'], 'ImageMap')
        self.assertTrue(pathlib.Path(tile['parameters']['texture']).is_file())
        self.assertEqual(tile['parameters']['scale'], [4.0, 4.0])
        self.assertEqual(tile['parameters']['gamma'], 0)
        # Its slope beside it, for MoonLightIPR's shading.
        self.assertTrue(tile['_slope'].endswith('.slope.pfm') and pathlib.Path(tile['_slope']).is_file())

    def test_an_ocean_wired_into_a_vector_displacement_is_its_tile(self):
        g = nodes.new('DwaBaseMaterial', {'albedo': [0.02, 0.05, 0.08]})
        g['nodes']['sea'] = {'type': 'ocean', 'parameters': {'resolution': 64, 'repeat': [3, 3], 'wind_speed': 12}, 'inputs': {},
                             'position': [0, 0]}
        g['nodes']['push'] = {'type': 'VectorDisplacement', 'parameters': {'factor': 2.0, 'bound_padding': 0.0},
                              'inputs': {'vector': 'sea'}, 'position': [0, 0]}
        g['displacement'] = 'push'
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(1.0):
            v = nodes.validate(g)
        self.assertEqual(v['nodes']['sea']['type'], 'ImageMap')
        self.assertEqual(v['nodes']['sea']['parameters']['scale'], [3.0, 3.0])
        # Room for the waves, at the node's factor.
        self.assertAlmostEqual(v['nodes']['push']['parameters']['bound_padding'],
                               2.0 * ocean.reach(ocean.settings({'wind_speed': 12})), places=5)
        # MoonLightIPR displaces by it and shades its slope.
        from moonray_modo import moonlightipr_materials
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(1.0):
            leaves, program = moonlightipr_materials.displacement_tree({'node_graph': g}, lambda what: None)
        self.assertEqual(program[0][:2], (moonlightipr_materials.OP_VECTOR, 2.0))
        self.assertEqual([layer['effect'] for layer in leaves[0][2]], ['_disp0', '_slope'])

    def test_each_frame_its_own_tile_and_none_made_outside_a_render(self):
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}):
            named = nodes.validate(graph())
            self.assertFalse(any(pathlib.Path(self.folder.name).iterdir()))
            files = []
            for time in (0.0, 1.0 / 24):
                with ocean.writing(time):
                    g = nodes.validate(graph())
                files.append(g['nodes'][g['nodes']['sea']['inputs']['vector']]['parameters']['texture'])
        self.assertNotEqual(files[0], files[1])
        self.assertEqual(named['nodes'][named['nodes']['sea']['inputs']['vector']]['parameters']['texture'], files[0])

    def test_off_in_the_overrides_the_surface_stays_flat(self):
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '0'}), ocean.writing(1.0):
            g = nodes.validate(graph())
        sea = g['nodes'][g['displacement']]
        self.assertEqual(sea['parameters']['factor'], 0.0)
        self.assertEqual(sea['inputs'], {})
        self.assertFalse(any(pathlib.Path(self.folder.name).iterdir()))

    def test_foam_is_an_image_of_the_tiles_foam(self):
        g = graph()
        g['nodes']['foam'] = {'type': 'ocean_foam', 'parameters': {'resolution': 64}, 'inputs': {}, 'position': [0, 0]}
        g['nodes']['surface']['inputs']['albedo'] = 'foam'
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(1.0):
            v = nodes.validate(g)
        self.assertEqual(v['nodes']['foam']['type'], 'ImageMap')
        self.assertTrue(v['nodes']['foam']['parameters']['texture'].endswith('.foam.pfm'))

    def test_foam_with_no_settings_follows_the_ocean_node(self):
        g = graph(wind_speed=17, repeat=[3, 3])
        g['nodes']['foam'] = {'type': 'ocean_foam', 'parameters': {}, 'inputs': {}, 'position': [0, 0]}
        g['nodes']['surface']['inputs']['albedo'] = 'foam'
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(1.0):
            v = nodes.validate(g)
        tile = v['nodes'][v['nodes']['sea']['inputs']['vector']]['parameters']['texture']
        self.assertEqual(v['nodes']['foam']['parameters']['texture'], tile.replace('.displacement.pfm', '.foam.pfm'))
        self.assertEqual(v['nodes']['foam']['parameters']['scale'], [3.0, 3.0])

    def test_the_editor_still_sees_the_ocean_node(self):
        self.assertEqual(nodes.effective(graph())['nodes']['sea']['type'], 'ocean')
        # A vector texture, for a Vector Displacement's Vector.
        self.assertEqual(nodes.category('ocean'), 'map')
        self.assertEqual(nodes.category('ocean_foam'), 'map')
        self.assertIn('wind_speed', nodes.specs('ocean'))

    def test_the_scene_writers_make_the_frames_tile(self):
        from moonray_modo import rdla
        scene = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 5, 30, 1], 'focal_mm': 35.0, 'film_mm': 36.0},
                 'materials': {'sea': {'native_shader': 'DwaBaseMaterial', 'native_parameters': {}, 'node_graph': graph(),
                                       'node_override': True, 'color': [.1, .1, .1]}},
                 'meshes': [{'name': 'Sea', 'identity': 'sea', 'vertices': [[-50, 0, -50], [50, 0, -50], [50, 0, 50], [-50, 0, 50]],
                             'faces': [[0, 3, 2, 1]], 'material': 'sea', 'uvs': [[0, 0], [0, 1], [1, 1], [1, 0]]}],
                 'lights': [], 'environments': [], 'time': 3.0}
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}):
            text = rdla.scene_text(scene, 64, 36, 1, 0.2)
        self.assertIn('VectorDisplacement(', text)
        self.assertTrue(any(pathlib.Path(self.folder.name).glob('*.displacement.pfm')))

    def test_moonray_gets_the_long_waves_and_a_normal_map(self):
        # Small ocean waves as shading (native.ocean_split): MoonRay's scene dices the sea at the ocean's resolution,
        # displaces it by the long waves and gives the rest to the material's Input Normal; off, the tile whole as before.
        import re
        from moonray_modo import rdla

        def written(switch):
            scene = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 2, 30, 1], 'focal_mm': 35.0, 'film_mm': 36.0},
                     'materials': {'sea': {'native_shader': 'DwaBaseMaterial', 'native_parameters': {},
                                           'node_graph': graph(resolution=256, fit_to_mesh=False, repeat=[4, 4]),
                                           'node_override': True, 'color': [.1, .1, .1]}},
                     'meshes': [{'name': 'Sea', 'identity': 'sea', 'vertices': [[-160, 0, -160], [160, 0, -160], [160, 0, 160], [-160, 0, 160]],
                                 'faces': [[0, 3, 2, 1]], 'material': 'sea', 'uvs': [[0, 0], [0, 1], [1, 1], [1, 0]],
                                 'subdivision': True, 'adaptive_error': 1.0}],
                     'lights': [], 'environments': [], 'time': 0.0}
            with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1', 'MOONRAY_MODO_OCEAN_SPLIT': switch}):
                return rdla.scene_text(scene, 640, 360, 1, 0.2)

        text = written('1')
        self.assertEqual(re.search(r'\["mesh_resolution"\] = (\d+)', text).group(1), str(ocean.OCEAN_RESOLUTION))
        self.assertIn('__long', text)
        self.assertRegex(text, r'\["input_normal"\] = ImageNormalMap\("[^"]*__short_normal"\)')
        self.assertRegex(text, r'\["tangent_space_normal_texture"\] = "[^"]*\.tx"')
        # A mesh edge of 320 m over 32 steps, tiles 80 m wide: steps an eighth of a tile apart, waves of 4 tiles and
        # longer kept, a power of two: 2 cycles across the tile.
        self.assertTrue(any(pathlib.Path(self.folder.name).glob('*.split2.coarse.pfm')))
        self.assertTrue(any(pathlib.Path(self.folder.name).glob('*.split2.fine.pfm')))
        text = written('0')
        self.assertEqual(re.search(r'\["mesh_resolution"\] = (\d+)', text).group(1), '8')
        self.assertNotIn('__long', text)
        self.assertNotIn('__short_normal', text)

    def test_moonlightipr_keeps_the_tile_whole(self):
        # A sea told how MoonRay dices it (_spacing) is split only in MoonRay's scene writer (nodes.emit): MoonLightIPR's
        # displacement reads the whole tile and its slope.
        g = graph(resolution=64)
        g['nodes']['sea']['_spacing'] = 1 / 64.0
        from moonray_modo import moonlightipr_materials
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(1.0):
            leaves, _ = moonlightipr_materials.displacement_tree({'node_graph': g}, lambda what: None)
        paths = [layer['path'] for layer in leaves[0][2]]
        self.assertTrue(paths[0].endswith('.displacement.pfm') and paths[1].endswith('.slope.pfm'))
        self.assertFalse(any(pathlib.Path(self.folder.name).glob('*.split*')))
        self.assertIsNone(ocean.CONTEXT['time'])


if __name__ == '__main__':
    unittest.main()
