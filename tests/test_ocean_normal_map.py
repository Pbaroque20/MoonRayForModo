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


if __name__ == '__main__':
    unittest.main()
