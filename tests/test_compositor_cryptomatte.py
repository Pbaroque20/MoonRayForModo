"""The compositor's Cryptomatte node: a matte by a name or ID given in a Cryptomatte tab, made into a picture before the
graph is run, and the IDs a matte's name stands for."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import compositor, cryptomatte, cryptomatte_pick


def graph():
    return {'nodes': {'m': {'type': 'cryptomatte', 'parameters': {'category': 'object', 'matte': 'pair'}, 'inputs': {}},
                      'b': {'type': 'input', 'parameters': {'buffer': 'beauty'}, 'inputs': {}},
                      'g': {'type': 'merge', 'parameters': {'mode': 'multiply'}, 'inputs': {'a': 'b', 'b': 'm'}},
                      'out': {'type': 'output', 'parameters': {}, 'inputs': {'image': 'g'}}}, 'root': 'out'}


class Node(unittest.TestCase):
    def test_it_is_a_matte_node_with_a_kind_and_a_matte(self):
        checked = compositor.validate(graph())
        self.assertEqual(checked['nodes']['m']['parameters'], {'category': 'object', 'matte': 'pair'})
        self.assertEqual(compositor.mattes(graph()), [('object', 'pair')])
        with self.assertRaises(ValueError):
            compositor.validate({'nodes': {'m': {'type': 'cryptomatte', 'parameters': {'category': 'asset'}, 'inputs': {}},
                                           'out': {'type': 'output', 'parameters': {}, 'inputs': {'image': 'm'}}}, 'root': 'out'})

    def test_it_becomes_a_buffer_of_its_matte_before_the_graph_is_run(self):
        made = []
        ran, files = compositor.lowered(graph(), {'beauty': 'b.exr'}, lambda category, matte: made.append((category, matte)) or 'matte.pfm')
        node = ran['nodes']['m']
        self.assertEqual(node['type'], 'input')
        self.assertEqual(files[node['parameters']['buffer']], 'matte.pfm')
        self.assertEqual(made, [('object', 'pair')])
        self.assertIn(node['parameters']['buffer'], compositor.buffers(ran))
        self.assertNotIn(node['parameters']['buffer'], compositor.buffers(graph()))

    def test_the_probe_leaves_it_unknown(self):
        got = compositor.sample(graph(), {'beauty': (1.0, 1.0, 1.0)}.get, 0, 0, 4, 4)
        self.assertIsNone(got['m'])


class Ids(unittest.TestCase):
    def test_a_number_and_a_name(self):
        self.assertEqual(cryptomatte_pick.ids_of({}, 'object', '#77'), [cryptomatte.bits(77)])
        snapshot = {'meshes': [{'name': 'A', 'identity': 'a'}, {'name': 'B', 'identity': 'b'}, {'name': 'C', 'identity': 'c'}],
                    'cryptomatte_objects': {'a': {'name': 'pair', 'id': 0}, 'b': {'name': 'pair', 'id': 0}}}
        self.assertEqual(cryptomatte_pick.ids_of({'snapshot': snapshot}, 'object', 'pair'), [cryptomatte.bits(cryptomatte.hash32('pair'))])
        self.assertEqual(cryptomatte_pick.ids_of({'snapshot': snapshot}, 'object', 'nobody'), [])

    def test_the_output_a_kind_is_in(self):
        snapshot = {'custom_aovs': [{'name': 'crypto_material', 'kind': 'cryptomatte', 'category': 'material'}]}
        self.assertEqual(cryptomatte_pick.buffer_of(snapshot, 'material'), 'crypto_material')
        self.assertIsNone(cryptomatte_pick.buffer_of(snapshot, 'object'))


if __name__ == '__main__':
    unittest.main()
