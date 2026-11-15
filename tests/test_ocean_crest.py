"""The Ocean Crest node: a mask of where an ocean's waves stand highest (0 below Crest Start's share of the sea's
height, rising to 1 at it), for the light that shines through the crests. Made per tile from each tile's displacement,
measured against the whole sea's height, and screened over the cascades as the foam is, so that MoonLightIPR draws a Mix
it drives without baking. The Ocean Plane mixes its Crest Colour into the water by it, under the foam."""
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

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def graph(**params):
    g = nodes.new('DwaBaseMaterial', {'albedo': [0.02, 0.05, 0.08], 'roughness': 0.05})
    g['nodes']['sea'] = {'type': 'ocean', 'parameters': dict({'resolution': 64}, **params), 'inputs': {}, 'position': [0, 0]}
    g['nodes']['push'] = {'type': 'VectorDisplacement', 'parameters': {}, 'inputs': {'vector': 'sea'}, 'position': [0, 0]}
    g['displacement'] = 'push'
    g['nodes']['crest'] = {'type': 'ocean_crest', 'parameters': {}, 'inputs': {}, 'position': [0, 0]}
    g['nodes']['glow'] = {'type': 'mix', 'position': [0, 0], 'inputs': {'mix': 'crest'},
                          'parameters': {'bg': [0.004, 0.018, 0.026], 'fg': [0.03, 0.15, 0.12], 'mix': 0.0}}
    g['nodes']['foam'] = {'type': 'ocean_foam', 'parameters': {}, 'inputs': {}, 'position': [0, 0]}
    g['nodes']['colour'] = {'type': 'mix', 'position': [0, 0], 'inputs': {'mix': 'foam', 'bg': 'glow'},
                            'parameters': {'bg': [0.0] * 3, 'fg': [0.9] * 3, 'mix': 0.0}}
    g['nodes']['surface']['inputs']['albedo'] = 'colour'
    return g


class Crest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.patch = mock.patch('moonray_modo.ocean.folder', return_value=pathlib.Path(self.folder.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.folder.cleanup()

    def test_the_mask_follows_the_heights(self):
        value = ocean.settings({'resolution': 64, 'cascades': False, 'crest_start': 0.25})
        with ocean.writing(1.3):
            path = ocean.crest_tile(value, value)
            displacement = ocean.make(value, 1.3)[0]
        width, mask = ocean.read_pfm(path)
        _, vectors = ocean.read_pfm(displacement)
        self.assertEqual(width, 64)
        reference = ocean.crest_reference(value)
        for i in range(0, width * width, 37):
            h, m = vectors[3 * i + 1], mask[3 * i]
            expected = min(1.0, max(0.0, (h / reference - 0.25) / 0.75))
            self.assertAlmostEqual(m, expected, places=5)
            self.assertEqual(mask[3 * i + 1], m)
        self.assertGreater(max(mask), 0.2)          # the highest crests glow
        self.assertEqual(min(mask), 0.0)            # the troughs not at all

    def test_crest_start_does_not_remake_the_waves(self):
        a = ocean.settings({'crest_start': 0.2})
        b = ocean.settings({'crest_start': 0.5})
        self.assertEqual(ocean.key(a, 1.0), ocean.key(b, 1.0))
        self.assertNotEqual(ocean.crest_path(a, a, 1.0), ocean.crest_path(a, b, 1.0))
        with self.assertRaises(ValueError):
            ocean.settings({'crest_start': 1.0})

    def test_screened_over_the_cascades_and_the_swell(self):
        g = graph(repeat=[4, 4], swell_height=2.0)
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(2.0):
            v = nodes.expand_ocean(nodes.effective(g))
        members = v['nodes']
        tiles = sorted(k for k in members if k.startswith('crest__cascade') and members[k].get('type') == 'ImageMap')
        self.assertEqual(len(tiles), 5)           # the swell and four cascades
        for name in tiles:
            self.assertIn('.crest', members[name]['parameters']['texture'])
            self.assertTrue(pathlib.Path(members[name]['parameters']['texture']).is_file())
            self.assertNotIn('_slope', members[name])
        # The glow follows the sea's own settings (the crest node has none of its own), turned as its tiles are.
        for index in range(5):
            self.assertEqual(members['crest__cascade%d' % index]['parameters'].get('rotation_angle'),
                             members['sea__cascade%d' % index]['parameters'].get('rotation_angle'))
        self.assertEqual([k for k in members if k.startswith('glow__foam')], ['glow__foam0', 'glow__foam1', 'glow__foam2', 'glow__foam3'])

    def test_crest_start_alone_still_follows_the_sea(self):
        g = graph(repeat=[4, 4], wind_speed=15.0)
        g['nodes']['crest']['parameters'] = {'crest_start': 0.5}
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(2.0):
            v = nodes.expand_ocean(nodes.effective(g))
        sea = pathlib.Path(v['nodes']['sea__cascade0']['parameters']['texture']).name.split('.')[0]
        crest = pathlib.Path(v['nodes']['crest__cascade0']['parameters']['texture']).name.split('.')[0]
        self.assertEqual(sea, crest)

    def test_moonlightipr_draws_it_without_baking(self):
        from moonray_modo import moonlightipr_materials
        notes = []
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), ocean.writing(2.0), \
                mock.patch('moonray_modo.graph_bake.bake', side_effect=AssertionError('baked')):
            layers = moonlightipr_materials.graph_layers({'node_graph': graph(repeat=[4, 4]), 'native_parameters': {}}, notes.append)
        # Four crest masks, then four foam masks over them.
        self.assertEqual(sum(1 for layer in layers if layer.get('effect') == 'layerMask'), 8)

    def test_the_ocean_plane_glows_under_its_foam(self):
        from moonray_modo import ocean_plane
        item = {'class': 'OceanPlaneGeometry', 'name': 'Ocean Plane', 'identity': 'plane1', 'parameters': {},
                'matrix': IDENTITY}
        snap = {'camera': {'matrix': IDENTITY, 'focal_mm': 35.0, 'film_mm': 36.0}, 'materials': {}, 'meshes': [],
                'entities': [item], 'lights': [], 'environments': [], 'time': 0.0}
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}):
            result = ocean_plane.apply(snap, [])
        g = result['materials'][result['meshes'][0]['material']]['node_graph']['nodes']
        self.assertEqual(g['crest']['type'], 'ocean_crest')
        self.assertEqual(g['glow']['inputs'], {'mix': 'crest'})
        self.assertEqual(g['glow']['parameters']['fg'], [0.03, 0.15, 0.12])
        self.assertEqual(g['colour']['inputs']['bg'], 'glow')
        self.assertIn('crest_start', ocean_plane.OCEAN_KEYS)

    def test_the_ocean_plane_has_its_roughness(self):
        from moonray_modo import ocean_plane
        item = {'class': 'OceanPlaneGeometry', 'name': 'Ocean Plane', 'identity': 'plane1',
                'parameters': {'roughness': 0.12, 'foam_roughness': 0.7}, 'matrix': IDENTITY}
        snap = {'camera': {'matrix': IDENTITY, 'focal_mm': 35.0, 'film_mm': 36.0}, 'materials': {}, 'meshes': [],
                'entities': [item], 'lights': [], 'environments': [], 'time': 0.0}
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}):
            result = ocean_plane.apply(snap, [])
        material = result['materials'][result['meshes'][0]['material']]
        g = material['node_graph']['nodes']
        self.assertEqual(g['rough']['parameters']['bg'], [0.12] * 3)
        self.assertEqual(g['rough']['parameters']['fg'], [0.7] * 3)
        self.assertEqual(material['roughness'], 0.12)


if __name__ == '__main__':
    unittest.main()
