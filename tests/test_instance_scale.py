"""Displaced instances: their even scale goes into the mesh's points (MoonRay displaces an instancer's reference in its
own space), and the reference is diced finely enough for its nearest placement (instanced_resolution)."""
import sys
import pathlib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import instance_scale, rdla  # noqa: E402


def scaled(s, x=0.0):
    return [s, 0, 0, 0, 0, s, 0, 0, 0, 0, s, 0, x, 0.01, 0, 1]


def scene(instances, displaced=True):
    graph = {'nodes': {}, 'displacement': 'node_v'} if displaced else {'nodes': {}}
    return {'materials': {'Sea': {'node_graph': graph}},
            'meshes': [{'name': 'Sea', 'material': 'Sea', 'vertices': [[-0.5, 0, -0.5], [0.5, 0, -0.5], [0.5, 0, 0.5], [-0.5, 0, 0.5]],
                        'faces': [[0, 3, 2, 1]], 'matrix': scaled(27.31), 'instances': instances}]}


def world(point, matrix):
    return [sum(point[k] * matrix[4 * k + c] for k in range(3)) + matrix[12 + c] for c in range(3)]


class InstanceScale(unittest.TestCase):
    def test_even_scale_moves_into_points(self):
        before = scene([scaled(27.31), scaled(27.31, 27.31)])
        after = instance_scale.baked(before)
        mesh, held = after['meshes'][0], before['meshes'][0]
        self.assertAlmostEqual(mesh['baked_instance_scale'], 27.31, 4)
        self.assertAlmostEqual(mesh['vertices'][1][0], 0.5 * 27.31, 4)
        self.assertAlmostEqual(instance_scale._scale(mesh['instances'][0]), 1.0, 5)
        for old, new in zip(held['instances'], mesh['instances']):
            for p, q in zip(held['vertices'], mesh['vertices']):
                for a, b in zip(world(p, old), world(q, new)):
                    self.assertAlmostEqual(a, b, 4)
        self.assertIs(before['meshes'][0], held)  # the scene read is left as it was

    def test_left_alone(self):
        for case in (scene([scaled(2.0), scaled(3.0)]),          # instances scaled unalike
                     scene([scaled(2.0)], displaced=False),       # nothing displaced
                     scene([scaled(1.0)])):                       # no scale
            self.assertIs(instance_scale.baked(case), case)

    def test_only_a_sea_is_diced_for_its_nearest_placement(self):
        # A displaced instancer that wears no sea keeps its level's resolution (2 to the level): given to every displaced
        # instancer, a tester's floor of 17 placed tiles came out at 256, past the 64 XPU2 takes, and the whole scene
        # went to MoonRay XPU. A sea (ocean.ocean_tags) is diced for its nearest placement as before.
        import re
        from unittest import mock
        from moonray_modo import nodes, node_defaults
        graph = nodes.new('DwaBaseMaterial', {'albedo': [.5, .5, .5]})
        graph['nodes']['push'] = {'type': 'NormalDisplacement', 'position': [0, 0], 'inputs': {},
                                  'parameters': node_defaults.parameters('NormalDisplacement')}
        graph['displacement'] = 'push'
        tiles = [scaled(1.0, float(x)) for x in range(17)]
        made = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 2, 1], 'focal_mm': 35.0, 'film_mm': 36.0},
                'materials': {'Floor': {'native_shader': 'DwaBaseMaterial', 'native_parameters': {}, 'node_graph': graph,
                                        'node_override': True, 'color': [.5, .5, .5]}},
                'meshes': [{'name': 'Floor', 'identity': 'floor', 'material': 'Floor', 'subdivision': True,
                            'vertices': [[-0.5, 0, -0.5], [0.5, 0, -0.5], [0.5, 0, 0.5], [-0.5, 0, 0.5]], 'faces': [[0, 3, 2, 1]],
                            'uvs': [[0, 0], [0, 1], [1, 1], [1, 0]], 'instances': tiles}],
                'lights': [], 'environments': [], 'time': 0.0}

        def resolution(sea):
            with mock.patch('moonray_modo.ocean.ocean_tags', return_value={'Floor'} if sea else set()):
                text = rdla.scene_text(made, 1920, 1080, 1, 0.2)
            return int(re.search(r'\["mesh_resolution"\] = (\d+)', text).group(1))
        self.assertEqual(resolution(False), 8)
        self.assertGreater(resolution(True), 8)

    def test_reference_diced_for_nearest_placement(self):
        mesh = instance_scale.baked(scene([scaled(27.31)]))['meshes'][0]
        near = {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 2, 0, 1], 'focal_mm': 50, 'film_mm': 36}
        far = dict(near, matrix=near['matrix'][:12] + [0, 2, 50000, 1])
        fine = rdla.instanced_resolution(mesh, {'camera': near}, 1920, 8, 'fine', 1.0)
        self.assertEqual(fine, rdla.INSTANCED_SPLITS)
        self.assertEqual(rdla.instanced_resolution(mesh, {'camera': near}, 1920, 8, 'coarse', 1.0), rdla.INSTANCED_COARSE_SPLITS)
        self.assertEqual(rdla.instanced_resolution(mesh, {'camera': far}, 1920, 8, 'fine', 1.0), 8)


if __name__ == '__main__':
    unittest.main()
