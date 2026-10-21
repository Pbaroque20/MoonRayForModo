"""MoonLightIPR's displacement: which materials displace and by how far (a node graph's NormalDisplacement ahead of
Shader Tree displacement layers, as rdla gives MoonRay them), and how a displaced mesh is packed (split so many times,
its materials' distances after its data, a key of its own)."""
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_materials as materials, moonlightipr_scene as scene


def graph(kind='NormalDisplacement', wired=True, **parameters):
    from moonray_modo import nodes
    made = nodes.new('DwaBaseMaterial', {'roughness': .5})
    made['nodes']['lift'] = {'type': kind, 'inputs': {'height': 'heights'} if wired and kind == 'NormalDisplacement' else {},
                             'parameters': parameters}
    if wired:
        made['nodes']['heights'] = {'type': 'image', 'inputs': {}, 'parameters': {'file': 'heights.png'}}
    made['displacement'] = 'lift'
    return made


class Displacement(unittest.TestCase):
    def test_nothing_displaces(self):
        self.assertIsNone(materials.displacement({'layers': [{'effect': 'diffCol'}]}))

    def test_shader_tree_layers_by_the_displacement_distance(self):
        self.assertEqual(materials.displacement({'layers': [{'effect': 'displace'}], 'displacement_distance': .3}), .3)

    def test_a_graph_by_its_height_multiplier(self):
        found = materials.graph_displacement({'node_graph': graph(height_multiplier=.1, zero_value=.2)}, lambda what: None, with_layers=False)
        self.assertEqual(found[1:], (0.0, .2, .1))
        self.assertEqual(materials.displacement({'node_graph': graph(height_multiplier=.1), 'layers': [{'effect': 'displace'}],
                                                 'displacement_distance': .3}), .1)

    def test_an_unwired_height_is_its_value(self):
        found = materials.graph_displacement({'node_graph': graph(wired=False, height=.5)}, lambda what: None, with_layers=False)
        self.assertEqual(found[1], .5)

    def test_other_displacement_nodes_are_named(self):
        named = []
        self.assertIsNone(materials.graph_displacement({'node_graph': graph('VectorDisplacement')}, named.append, with_layers=False))
        self.assertEqual(named, ['a VectorDisplacement displacement node'])


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
        self.assertEqual(struct.unpack_from('<If', payload, 16), (1, .25))

    def test_an_undisplaced_mesh_is_left_alone(self):
        mesh = {'name': 'Plane', 'faces': [[0, 1, 2]], 'material': ''}
        self.assertEqual(scene.displaced(mesh, b'k' * 8, 0, b'data', {'': {}}, {'': 0}, []), (b'k' * 8, 0, b'data'))


if __name__ == '__main__':
    unittest.main()
