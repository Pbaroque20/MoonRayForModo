"""A map laid out in the object's space (a noise wired into a Vector Displacement, a tester's ocean) is baked for
MoonLightIPR over the box its meshes fill and read by where each point is in its object (graph_bake.solid, solid_frame,
moonlightipr_scene.solid_regions), not over one unit of space stretched across the UVs, which showed it nearly flat."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import graph_bake, moonlightipr_scene, nodes  # noqa: E402


def noisy(space):
    graph = nodes.new('DwaBaseMaterial', {})
    graph['nodes']['noise'] = {'type': 'NoiseMap_v2', 'parameters': {'space': space}, 'inputs': {}, 'position': [0, 0]}
    graph['nodes']['push'] = {'type': 'VectorDisplacement', 'parameters': {'factor': 0.75}, 'inputs': {'vector': 'noise'},
                              'position': [0, 0]}
    graph['displacement'] = 'push'
    return graph


class Solid(unittest.TestCase):
    def test_an_object_space_noise_is_solid_and_a_texture_space_one_is_not(self):
        self.assertEqual(graph_bake.solid(noisy(nodes.SPACE_OBJECT), 'noise'), ['noise'])
        self.assertEqual(graph_bake.solid(noisy(nodes.SPACE_TEXTURE), 'noise'), [])
        self.assertEqual(graph_bake.plan(noisy(nodes.SPACE_OBJECT), 'noise'), (None, None))

    def test_the_frame_lies_across_the_thinnest_side_and_maps_the_box_into_the_square(self):
        region = {'low': [-10.0, -0.5, -4.0], 'high': [10.0, 0.5, 4.0]}
        square, camera, side, rows = graph_bake.solid_frame(region)
        self.assertAlmostEqual(side, 20.4)

        def uv(point):
            return (sum(r * p for r, p in zip(rows[0:3], point)) + rows[3], sum(r * p for r, p in zip(rows[4:7], point)) + rows[7])
        # x along u and z along v, the box inside the square, its middle in the middle.
        for point in ([-10, 0, -4], [10, 0, 4], [0, 0, 0]):
            u, v = uv(point)
            self.assertTrue(0 <= u <= 1 and 0 <= v <= 1)
        self.assertEqual([round(c, 6) for c in uv([0, 0, 0])], [0.5, 0.5])
        # The bake's square puts its unit corner where the rows read u = v = 1.
        corner = [square[0] + square[4] + square[12], square[1] + square[5] + square[13], square[2] + square[6] + square[14]]
        self.assertEqual([round(c, 6) for c in uv(corner)], [1.0, 1.0])
        # The camera looks at the square from the side its normal points to.
        normal, eye = square[8:11], camera[12:15]
        self.assertGreater(sum(n * (e - c) for n, e, c in zip(normal, eye, [0.0, 0.0, 0.0])), 0)

    def test_the_bake_scene_lays_the_noise_over_the_box(self):
        region = {'low': [-10.0, 0.0, -4.0], 'high': [10.0, 0.0, 4.0]}
        made = graph_bake.scene(noisy(nodes.SPACE_OBJECT), 'noise', region=region)
        self.assertEqual(made['width'], graph_bake.SOLID_RESOLUTION)
        self.assertAlmostEqual(made['camera']['ortho_width'], 20.4)
        self.assertEqual(made['materials']['bake']['node_graph']['nodes']['noise']['parameters']['space'], nodes.SPACE_WORLD)
        self.assertEqual(made['meshes'][0]['matrix'], graph_bake.solid_frame(region)[0])
        # Without a box (the graph editor's previews), as before.
        self.assertNotIn('matrix', graph_bake.scene(noisy(nodes.SPACE_OBJECT), 'noise')['meshes'][0])

    def test_the_packer_gives_each_such_material_its_meshes_box(self):
        materials = {'sea': {'node_graph': noisy(nodes.SPACE_OBJECT), 'native_shader': 'DwaBaseMaterial', 'node_override': True},
                     'red': {'color': [1, 0, 0]}}
        meshes = [{'name': 'Plane', 'material': 'sea', 'vertices': [[-10, 0, -4], [10, 0, -4], [10, 1, 4]], 'faces': [[0, 1, 2]]},
                  {'name': 'Ball', 'material': 'red', 'vertices': [[50, 50, 50]], 'faces': []}]
        held = moonlightipr_scene.solid_regions(meshes, materials)
        self.assertEqual(held['sea']['_object_region'], {'low': [-10.0, 0.0, -4.0], 'high': [10.0, 1.0, 4.0]})
        self.assertNotIn('_object_region', held['red'])


if __name__ == '__main__':
    unittest.main()
