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
        for bad in ({'resolution': 100}, {'wind_speed': 0}, {'size': -1}, {'choppiness': -1}, {'depth': float('nan')}):
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
            out = [pathlib.Path(folder) / 'd.pfm', pathlib.Path(folder) / 'f.pfm']
            self.assertTrue(ocean.native_tile(value, 2.5, out[0], out[1], dll))
            data = out[0].read_bytes().split(b'\n', 3)[3]
            got = array.array('f')
            got.frombytes(data[:64 * 64 * 12])
            mask = array.array('f')
            mask.frombytes(out[1].read_bytes().split(b'\n', 3)[3][:64 * 64 * 4])
        for a, b in zip((c for v in expected for c in v), got):
            self.assertAlmostEqual(a, b, places=4)
        for a, b in zip(foam, mask):
            self.assertAlmostEqual(a, b, places=4)

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
        self.assertEqual(tile['type'], 'image')
        self.assertTrue(pathlib.Path(tile['parameters']['file']).is_file())
        self.assertEqual(tile['parameters']['scale'], [4.0, 4.0])
        self.assertFalse(tile['parameters']['srgb'])

    def test_each_frame_its_own_tile_and_none_made_outside_a_render(self):
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}):
            named = nodes.validate(graph())
            self.assertFalse(any(pathlib.Path(self.folder.name).iterdir()))
            files = []
            for time in (0.0, 1.0 / 24):
                with ocean.writing(time):
                    g = nodes.validate(graph())
                files.append(g['nodes'][g['nodes']['sea']['inputs']['vector']]['parameters']['file'])
        self.assertNotEqual(files[0], files[1])
        self.assertEqual(named['nodes'][named['nodes']['sea']['inputs']['vector']]['parameters']['file'], files[0])

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
        self.assertEqual(v['nodes']['foam']['type'], 'image')
        self.assertTrue(v['nodes']['foam']['parameters']['file'].endswith('.foam.pfm'))

    def test_foam_with_no_settings_follows_the_ocean_node(self):
        g = graph(wind_speed=17, repeat=[3, 3])
        g['nodes']['foam'] = {'type': 'ocean_foam', 'parameters': {}, 'inputs': {}, 'position': [0, 0]}
        g['nodes']['surface']['inputs']['albedo'] = 'foam'
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(1.0):
            v = nodes.validate(g)
        tile = v['nodes'][v['nodes']['sea']['inputs']['vector']]['parameters']['file']
        self.assertEqual(v['nodes']['foam']['parameters']['file'], tile.replace('.displacement.pfm', '.foam.pfm'))
        self.assertEqual(v['nodes']['foam']['parameters']['scale'], [3.0, 3.0])

    def test_the_editor_still_sees_the_ocean_node(self):
        self.assertEqual(nodes.effective(graph())['nodes']['sea']['type'], 'ocean')
        self.assertEqual(nodes.category('ocean'), 'displacement')
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
        self.assertIsNone(ocean.CONTEXT['time'])


if __name__ == '__main__':
    unittest.main()
