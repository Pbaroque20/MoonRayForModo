"""An Ocean node fitted to the meshes its material is on (ocean.uv_metres, ocean.fitted): Tiles Across tiles across the
mesh's U, sized to it whatever its size, its UVs and its scale, square along V; Repeat as set where Fit to
Mesh is off."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import nodes, ocean  # noqa: E402


def plane(width, depth, uv=(1.0, 1.0), scale=1.0, material='sea'):
    vertices = [[-width / 2, 0, -depth / 2], [width / 2, 0, -depth / 2], [width / 2, 0, depth / 2], [-width / 2, 0, depth / 2]]
    uvs = [[0, 0], [uv[0], 0], [uv[0], uv[1]], [0, uv[1]]]
    return {'name': 'Plane', 'vertices': vertices, 'faces': [[0, 1, 2, 3]], 'uvs': uvs, 'material': material,
            'matrix': [scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, scale, 0, 0, 0, 0, 1]}


def scene(meshes, **params):
    graph = nodes.new('DwaBaseMaterial', {})
    graph['nodes']['sea'] = {'type': 'ocean', 'parameters': dict(params), 'inputs': {}, 'position': [0, 0]}
    graph['nodes']['foam'] = {'type': 'ocean_foam', 'parameters': {}, 'inputs': {}, 'position': [0, 0]}
    return {'materials': {'sea': {'node_graph': graph}}, 'meshes': meshes}


def repeat(made):
    return made['materials']['sea']['node_graph']['nodes']['sea']['parameters']['repeat']


class Fit(unittest.TestCase):
    def test_the_metres_a_unit_of_uv_spans(self):
        self.assertEqual([round(v, 6) for v in ocean.uv_metres(plane(800, 400))[:2]], [800.0, 400.0])
        self.assertEqual([round(v, 6) for v in ocean.uv_metres(plane(800, 400, uv=(2, 4)))[:2]], [400.0, 100.0])
        self.assertEqual([round(v, 6) for v in ocean.uv_metres(plane(10, 10, scale=3))[:2]], [30.0, 30.0])
        self.assertIsNone(ocean.uv_metres(dict(plane(10, 10), uvs=[])))

    def test_tiles_across_the_mesh_whatever_its_size(self):
        def sea(made):
            return made['materials']['sea']['node_graph']['nodes']['sea']
        # Ten 80 m tiles across an 800 m plane: the sea at its own size.
        made = ocean.fitted(scene([plane(800, 800)]))
        self.assertEqual([round(v, 6) for v in repeat(made)], [10.0, 10.0])
        self.assertAlmostEqual(sea(made)['_scale'], 1.0)
        self.assertNotIn('size', sea(made)['parameters'])
        # Ten across a long thin plane, square: forty along it; each 4 m wide, the 80 m sea scaled to a twentieth.
        made = ocean.fitted(scene([plane(40, 160)]))
        self.assertEqual([round(v, 6) for v in repeat(made)], [10.0, 40.0])
        self.assertAlmostEqual(sea(made)['_scale'], 0.05)
        # Its own count, and the plane scaled.
        made = ocean.fitted(scene([plane(10, 10, scale=3)], tiles_across=3))
        self.assertEqual([round(v, 6) for v in repeat(made)], [3.0, 3.0])
        self.assertAlmostEqual(sea(made)['_scale'], 10.0 / 80.0)
        # The graph as the engines take it: the Vector Displacement it feeds scaled by as much, its padding with it.
        from unittest import mock
        import os
        graph = sea(made) and made['materials']['sea']['node_graph']
        graph['nodes']['push'] = {'type': 'VectorDisplacement', 'parameters': {'factor': 2.0}, 'inputs': {'vector': 'sea'},
                                  'position': [0, 0]}
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), mock.patch.object(ocean, 'tile', return_value=('d.pfm', 'f.pfm', 's.pfm')):
            expanded = nodes.expand_ocean(nodes.effective(graph))
        push = expanded['nodes']['push']['parameters']
        self.assertAlmostEqual(push['factor'], 2.0 * 10.0 / 80.0)
        value = ocean.settings(graph['nodes']['sea']['parameters'])
        self.assertAlmostEqual(push['bound_padding'], ocean.reach(value) * 10.0 / 80.0 * 2.0)

    def test_off_keeps_the_repeat_as_set(self):
        held = scene([plane(800, 800)], fit_to_mesh=False, repeat=[3.0, 3.0])
        self.assertIs(ocean.fitted(held), held)

    def test_no_mesh_wears_it_and_nothing_changes(self):
        held = scene([plane(800, 800, material='other')])
        self.assertIs(ocean.fitted(held), held)

    def test_an_ocean_has_no_size_and_an_old_graph_with_one_still_reads(self):
        self.assertNotIn('size', nodes.specs('ocean'))
        old = nodes.new('DwaBaseMaterial', {})
        old['nodes']['sea'] = {'type': 'ocean', 'parameters': {'size': 50.0, 'wind_speed': 9.0}, 'inputs': {}, 'position': [0, 0]}
        self.assertNotIn('size', nodes.effective(old)['nodes']['sea']['parameters'])
        self.assertEqual(ocean.settings({'size': 5.0})['size'], ocean.FITTED_SIZE)

    def test_the_foam_follows_the_fitted_ocean(self):
        made = ocean.fitted(scene([plane(800, 800)]))
        self.assertEqual(made['materials']['sea']['node_graph']['nodes']['foam']['parameters'], {})
        self.assertIn('fit_to_mesh', nodes.specs('ocean'))
        self.assertIn('tiles_across', nodes.specs('ocean'))


class RealtimeDicing(unittest.TestCase):
    def test_a_realtime_moonray_dices_a_displaced_sea_as_the_render(self):
        # The realtime cut's triangle budget counted the sea split evenly all over; MoonRay dices by the screen, and the
        # sea came out at 18 pixels where a render dices at 1, flattened.
        import os
        import re
        from unittest import mock
        from moonray_modo import rdla
        made = scene([plane(800, 800)])
        graph = made['materials']['sea']['node_graph']
        graph['nodes']['push'] = {'type': 'VectorDisplacement', 'parameters': {}, 'inputs': {'vector': 'sea'}, 'position': [0, 0]}
        graph['displacement'] = 'push'
        made['materials']['sea'].update(native_shader='DwaBaseMaterial', node_override=True)
        made['meshes'][0].update(identity='sea', vertices=[[x * 40.0 - 400, 0.0, z * 40.0 - 400] for z in range(21) for x in range(21)],
                                 faces=[[z * 21 + x, z * 21 + x + 1, (z + 1) * 21 + x + 1, (z + 1) * 21 + x] for z in range(20) for x in range(20)],
                                 uvs=[[(x + dx) / 20, (z + dz) / 20] for z in range(20) for x in range(20) for dx, dz in ((0, 0), (1, 0), (1, 1), (0, 1))])
        made.update(camera={'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 14, 300, 1], 'focal_mm': 35.0, 'film_mm': 36.0},
                    lights=[], environments=[])
        found = {}
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '0'}):
            for label, extra in (('render', {}), ('fine', {'_geometry_detail': 'fine'}), ('coarse', {'_geometry_detail': 'coarse'})):
                text = rdla.scene_text(dict(made, **extra), 960, 540, 1, 0.0)
                found[label] = float(re.search(r'\["adaptive_error"\] = ([0-9.e+-]+)', text).group(1))
        self.assertEqual(found['fine'], found['render'])
        self.assertLessEqual(found['coarse'], 2.0)


if __name__ == '__main__':
    unittest.main()
