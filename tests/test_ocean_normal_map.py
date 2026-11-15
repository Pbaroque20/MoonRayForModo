"""The ocean's short waves in MoonRay (nodes.split_ocean): the kit's ModoOceanNormalMap over an ImageMap of the split
tile where the runtime has it, at the strength that matches MoonLightIPR's sea and with mirror reflections kept above
the horizon; MoonRay's ImageNormalMap, as before, where it has not."""
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


def graph():
    g = nodes.new('DwaBaseMaterial', {'albedo': [0.02, 0.05, 0.08], 'roughness': 0.05})
    g['nodes']['sea'] = {'type': 'ocean', 'parameters': {'resolution': 64, 'repeat': [4, 4]}, 'inputs': {}, 'position': [0, 0],
                         '_spacing': 0.05}
    g['nodes']['push'] = {'type': 'VectorDisplacement', 'parameters': {}, 'inputs': {'vector': 'sea'}, 'position': [0, 0]}
    g['displacement'] = 'push'
    return g


class OceanNormalMap(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.patch = mock.patch('moonray_modo.ocean.folder', return_value=pathlib.Path(self.folder.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.folder.cleanup()

    def split(self, available):
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(2.0), \
                mock.patch('moonray_modo.ocean.normal_map_available', return_value=available):
            v = nodes.expand_ocean(nodes.effective(graph()))
            return nodes.split_ocean(v, 'surface')

    def test_the_kits_map_over_the_tiles_image(self):
        v = self.split(True)
        members = v['nodes']
        normal = members[members['surface']['inputs']['input_normal']]
        self.assertEqual(normal['type'], 'ocean_normal')
        self.assertEqual(normal['parameters'], {'horizon': ocean.HORIZON, 'dial': ocean.SHORT_WAVES_DIAL})
        image = members[normal['inputs']['input']]
        self.assertEqual(image['type'], 'ImageMap')
        self.assertTrue(image['parameters']['texture'].endswith('.fine.pfm'))
        self.assertEqual(image['parameters']['gamma'], 0)
        # Turned as the finest cascade's tile is.
        self.assertEqual(image['parameters']['rotation_angle'], ocean.TURNS[-1])

    def test_an_older_runtime_keeps_moonrays_image_normal_map(self):
        v = self.split(False)
        normal = v['nodes'][v['nodes']['surface']['inputs']['input_normal']]
        self.assertEqual(normal['type'], 'ImageNormalMap')

    def test_written_as_modo_ocean_normal_map(self):
        g = nodes.new('DwaBaseMaterial', {'albedo': [0.02, 0.05, 0.08]})
        g['nodes']['tile'] = {'type': 'ImageMap', 'parameters': {'texture': 'fine.pfm', 'gamma': 0}, 'inputs': {}, 'position': [0, 0]}
        g['nodes']['short'] = {'type': 'ocean_normal', 'parameters': {'horizon': 0.02, 'dial': 0.35}, 'inputs': {'input': 'tile'},
                               'position': [0, 0]}
        g['nodes']['surface']['inputs']['input_normal'] = 'short'
        lines = []
        with mock.patch('moonray_modo.map_library.emit', return_value='ImageMap("/t/tile")'):
            nodes.emit({'node_graph': g, 'color': [.5] * 3}, '/t', [0], lines, {}, validated=False)
        text = '\n'.join(lines)
        self.assertIn('ModoOceanNormalMap("/t/node/', text)
        self.assertIn('["input"] = bind(ImageMap("/t/tile"), Rgb(1,1,1))', text)
        self.assertIn('["dial"] = 0.35', text)
        self.assertIn('["input_normal"] = ModoOceanNormalMap(', text)


class HorizonFade(unittest.TestCase):
    """An Ocean Plane's waves fading out toward the horizon in MoonRay and XPU2 (ocean_plane.fade, nodes.fade_ocean)."""

    CAMERA = {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 5.6, 0, 1], 'focal_mm': 50.0, 'film_mm': 36.0}

    def test_along_the_view_where_a_pixel_spans_the_waves(self):
        from moonray_modo import ocean_plane
        faded = ocean_plane.fade(self.CAMERA, 1280, 0.0, 80.0)
        pixel = 36.0 / 50.0 / 1280
        near, far = ((waves * 80.0 * 5.6 / (2 * pixel)) ** 0.5 for waves in ocean_plane.FADE_WAVES)
        self.assertAlmostEqual(faded['start'][2], -near, places=3)
        self.assertAlmostEqual(faded['end'][2], -far, places=3)
        self.assertEqual(faded['start'][1], 0.0)
        # Looking straight down, or orthographic: none.
        self.assertIsNone(ocean_plane.fade({'matrix': [1, 0, 0, 0, 0, 0, -1, 0, 0, 1, 0, 0, 0, 5, 0, 1]}, 1280, 0.0, 80.0))
        self.assertIsNone(ocean_plane.fade(dict(self.CAMERA, projection='ortho'), 1280, 0.0, 80.0))

    def test_only_in_moonrays_reading(self):
        from moonray_modo import ocean_plane
        item = {'class': 'OceanPlaneGeometry', 'name': 'Ocean Plane', 'identity': 'plane1', 'parameters': {},
                'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}

        def sea(displaces):
            snap = {'camera': self.CAMERA, 'width': 1280, 'materials': {}, 'meshes': [], 'entities': [dict(item)],
                    'lights': [], 'environments': [], 'time': 0.0}
            # The reading's engine as host.by_engine sets it: MoonLightIPR's readings are made undisplaced.
            held = types.SimpleNamespace(modo_displaces=lambda: displaces)
            with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), mock.patch.dict(sys.modules, {'moonray_modo.host': held}):
                result = ocean_plane.apply(snap, [])
            return result['materials'][result['meshes'][0]['material']]['node_graph']['nodes']['sea']
        self.assertIn('_fade', sea(True))
        self.assertNotIn('_fade', sea(False))

    def test_the_waves_and_the_short_waves_times_the_gradient(self):
        g = graph()
        g['nodes']['sea']['_fade'] = {'start': [0, 0, -50], 'end': [0, 0, -900]}
        folder = tempfile.TemporaryDirectory()
        with mock.patch('moonray_modo.ocean.folder', return_value=pathlib.Path(folder.name)), \
                mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(2.0), \
                mock.patch('moonray_modo.ocean.normal_map_available', return_value=True):
            v = nodes.fade_ocean(nodes.split_ocean(nodes.expand_ocean(nodes.effective(g)), 'surface'))
        folder.cleanup()
        members = v['nodes']
        gradient = members['sea__fade']
        self.assertEqual(gradient['type'], 'GradientMap')
        self.assertEqual(gradient['parameters']['start'], [0, 0, -50])
        faded = members[members['push']['inputs']['vector']]
        self.assertEqual(faded['type'], 'multiply')
        self.assertEqual(faded['inputs']['in2'], 'sea__fade')
        normal = members[members['surface']['inputs']['input_normal']]
        flat = members[normal['inputs']['input']]
        self.assertEqual((flat['type'], flat['inputs']['mix'], flat['parameters']['bg']), ('mix', 'sea__fade', [0.5, 0.5, 1.0]))
        self.assertTrue(all('_fade' not in n for n in members.values()))


if __name__ == '__main__':
    unittest.main()
