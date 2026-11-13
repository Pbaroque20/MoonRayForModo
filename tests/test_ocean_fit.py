"""An Ocean node's repeat fitted to the meshes its material is on (ocean.uv_metres, ocean.fitted): its tiles Size metres
across whatever the mesh's size, its UVs and its scale; Repeat as set where Fit to Mesh is off."""
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
    graph['nodes']['sea'] = {'type': 'ocean', 'parameters': dict({'size': 80.0}, **params), 'inputs': {}, 'position': [0, 0]}
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

    def test_tiles_of_size_metres_on_any_plane(self):
        self.assertEqual([round(v, 6) for v in repeat(ocean.fitted(scene([plane(800, 800)])))], [10.0, 10.0])
        self.assertEqual([round(v, 6) for v in repeat(ocean.fitted(scene([plane(40, 160)])))], [0.5, 2.0])
        # The graph in the scene given is left as it was.
        held = scene([plane(800, 800)])
        ocean.fitted(held)
        self.assertNotIn('repeat', held['materials']['sea']['node_graph']['nodes']['sea']['parameters'])

    def test_off_keeps_the_repeat_as_set(self):
        held = scene([plane(800, 800)], fit_to_mesh=False, repeat=[3.0, 3.0])
        self.assertIs(ocean.fitted(held), held)

    def test_no_mesh_wears_it_and_nothing_changes(self):
        held = scene([plane(800, 800, material='other')])
        self.assertIs(ocean.fitted(held), held)

    def test_the_foam_follows_the_fitted_ocean(self):
        made = ocean.fitted(scene([plane(800, 800)]))
        self.assertEqual(made['materials']['sea']['node_graph']['nodes']['foam']['parameters'], {})
        self.assertIn('fit_to_mesh', nodes.specs('ocean'))


if __name__ == '__main__':
    unittest.main()
