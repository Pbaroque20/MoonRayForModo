"""MoonLightIPR's displacement: which materials displace and how, as a program the session runs at each vertex (a node
graph's displacement nodes ahead of Shader Tree displacement layers, as rdla gives MoonRay them: Normal and Vector
nodes its leaves, Combine and Switch nodes joining them), and how a displaced mesh is packed (split so many times, its
materials' programs after its data, a key of its own)."""
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_materials as materials, moonlightipr_scene as scene
from moonray_modo.moonlightipr_materials import OP_NORMAL, OP_VECTOR, OP_COMBINE, OP_NOTHING


def graph(displacement, extra):
    """A native material's graph whose displacement output is the node displacement, among the nodes extra."""
    from moonray_modo import nodes
    made = nodes.new('DwaBaseMaterial', {'roughness': .5})
    made['nodes'].update(extra)
    made['nodes']['heights'] = {'type': 'image', 'inputs': {}, 'parameters': {'file': 'heights.png'}}
    made['displacement'] = displacement
    return {'node_graph': made}


def normal(wired=True, **parameters):
    return {'type': 'NormalDisplacement', 'inputs': {'height': 'heights'} if wired else {}, 'parameters': parameters}


def program(material):
    return materials.displacement_tree(material, lambda what: None, with_layers=False)


class Displacement(unittest.TestCase):
    def test_nothing_displaces(self):
        self.assertIsNone(materials.displacement({'layers': [{'effect': 'diffCol'}]}))

    def test_shader_tree_layers_along_the_normal_by_the_displacement_distance(self):
        self.assertEqual(materials.displacement({'layers': [{'effect': 'displace'}], 'displacement_distance': .3}), [(OP_NORMAL, 0.0, .3, 0)])

    def test_a_normal_node_above_its_zero_value_by_its_multiplier(self):
        leaves, steps = program(graph('lift', {'lift': normal(height_multiplier=.1, zero_value=.2)}))
        self.assertEqual(steps, [(OP_NORMAL, .2, .1, 0)])
        self.assertEqual(leaves[0][:2], (0, [0.0] * 3))

    def test_a_graph_ahead_of_shader_tree_layers(self):
        held = dict(graph('lift', {'lift': normal(height_multiplier=.1)}), layers=[{'effect': 'displace'}], displacement_distance=.3)
        self.assertEqual(materials.displacement(held), [(OP_NORMAL, 0.0, .1, 0)])

    def test_an_unwired_height_is_its_value(self):
        leaves, _ = program(graph('lift', {'lift': normal(wired=False, height=.5)}))
        self.assertEqual(leaves[0][1], [.5] * 3)

    def test_a_vector_node_its_space_and_style(self):
        made = graph('push', {'push': {'type': 'VectorDisplacement', 'inputs': {},
                                       'parameters': {'vector': 'Vec3f(0.1f, 0.2f, 0.3f)', 'factor': 2.0, 'source_space': 1, 'tangent_space_style': 1}}})
        leaves, steps = program(made)
        self.assertEqual(steps, [(OP_VECTOR, 2.0, 0.0, 0 | 256 | 512)])
        self.assertEqual(leaves[0][1], [.1, .2, .3])

    def test_combine_joins_two_leaves_in_order(self):
        made = graph('both', {'one': normal(), 'two': normal(zero_value=.5),
                              'both': {'type': 'CombineDisplacement', 'inputs': {'input_1': 'one', 'input_2': 'two'},
                                       'parameters': {'scale_1': .5, 'scale_2': 2.0, 'operation': 1}}})
        leaves, steps = program(made)
        self.assertEqual([slot for slot, _, _ in leaves], [0, 1])
        self.assertEqual(steps, [(OP_NORMAL, 0.0, 1.0, 0), (OP_NORMAL, .5, 1.0, 1), (OP_COMBINE, .5, 2.0, 1)])

    def test_switch_takes_its_choice_cycling_through_sixteen(self):
        made = graph('pick', {'a': normal(height_multiplier=1.0), 'b': normal(height_multiplier=2.0),
                              'pick': {'type': 'SwitchDisplacement', 'inputs': {'displacement0': 'a', 'displacement1': 'b'},
                                       'parameters': {'choice': 17}}})
        self.assertEqual(program(made)[1], [(OP_NORMAL, 0.0, 2.0, 0)])

    def test_a_missing_input_is_no_displacement(self):
        made = graph('both', {'one': normal(), 'both': {'type': 'CombineDisplacement', 'inputs': {'input_1': 'one'}, 'parameters': {}}})
        self.assertEqual(program(made)[1][1], (OP_NOTHING, 0.0, 0.0, 0))

    def test_more_leaves_than_slots_are_named(self):
        named = []
        chain = {'n%d' % i: normal() for i in range(5)}
        chain.update({'c1': {'type': 'CombineDisplacement', 'inputs': {'input_1': 'n0', 'input_2': 'n1'}, 'parameters': {}},
                      'c2': {'type': 'CombineDisplacement', 'inputs': {'input_1': 'n2', 'input_2': 'n3'}, 'parameters': {}},
                      'c3': {'type': 'CombineDisplacement', 'inputs': {'input_1': 'c1', 'input_2': 'c2'}, 'parameters': {}},
                      'c4': {'type': 'CombineDisplacement', 'inputs': {'input_1': 'c3', 'input_2': 'n4'}, 'parameters': {}}})
        leaves, _ = materials.displacement_tree(graph('c4', chain), named.append, with_layers=False)
        self.assertEqual(len(leaves), 4)
        self.assertIn('more than 4 displacement nodes in one graph', named)


class Packing(unittest.TestCase):
    def test_a_displaced_mesh_is_split_and_keyed_apart(self):
        mesh = {'name': 'Plane', 'faces': [[0, 1, 2, 3]], 'material': 'lifted'}
        held = {'lifted': {'layers': [{'effect': 'displace'}], 'displacement_distance': .25}, '': {}}
        key, flags, payload = scene.displaced(mesh, b'k' * 8, 0, b'data', held, {'': 0, 'lifted': 1}, [])
        self.assertTrue(flags & scene.MESH_DISPLACE)
        self.assertNotEqual(key, b'k' * 8)
        levels, material, count = struct.unpack_from('<3I', payload, 4)
        self.assertEqual((material, count), (1, 1))
        self.assertLessEqual(2 * 4 ** levels, scene.DISPLACED_TRIANGLES)
        self.assertEqual(struct.unpack_from('<2I', payload, 16), (1, 1))
        self.assertEqual(struct.unpack_from('<I2fI', payload, 24), (OP_NORMAL, 0.0, .25, 0))

    def test_an_undisplaced_mesh_is_left_alone(self):
        mesh = {'name': 'Plane', 'faces': [[0, 1, 2]], 'material': ''}
        self.assertEqual(scene.displaced(mesh, b'k' * 8, 0, b'data', {'': {}}, {'': 0}, []), (b'k' * 8, 0, b'data'))


if __name__ == '__main__':
    unittest.main()
