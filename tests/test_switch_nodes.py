"""MoonRay's switch nodes: their 64 inputs numbered as MoonRay declares them (input0 to input63, displacement0 to
displacement63), and the switch displacement in the node editor. No Modo or renderer launch."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from moonray_modo import map_library, nodes, rdla
from test_production import scene


class SwitchNodeTests(unittest.TestCase):
    def test_switch_displacement_is_a_displacement_node(self):
        schema = map_library.catalog()['SwitchDisplacement']
        self.assertEqual(nodes.category('SwitchDisplacement'), 'displacement')
        self.assertEqual(sorted(k for k in schema['attributes'] if k.startswith('displacement')), sorted('displacement%d' % i for i in range(64)))
        self.assertTrue(nodes.connectable('SwitchDisplacement', 'displacement63'))
        self.assertTrue(nodes.connectable('SwitchDisplacement', 'choice'))

    def test_switch_displacement_written_with_numbered_inputs(self):
        value = scene()
        graph = nodes.new()
        graph['nodes']['low'] = {'type': 'NormalDisplacement', 'parameters': {'height': .05}}
        graph['nodes']['high'] = {'type': 'NormalDisplacement', 'parameters': {'height': .2}}
        graph['nodes']['pick'] = {'type': 'SwitchDisplacement', 'parameters': {'choice': 1.0}, 'inputs': {'displacement0': 'low', 'displacement1': 'high'}}
        graph['displacement'] = 'pick'
        value['materials']['']['node_graph'] = graph
        text = rdla.scene_text(value)
        self.assertIn('SwitchDisplacement(', text)
        self.assertRegex(text, r'\["displacement0"\] = NormalDisplacement\(')
        self.assertRegex(text, r'\["displacement1"\] = NormalDisplacement\(')
        self.assertIn('table.insert(a, displacements[tag])', text)

    def test_switch_maps_have_numbered_inputs_and_old_graphs_are_read(self):
        self.assertNotIn('input', map_library.catalog()['SwitchColorMap']['attributes'])
        self.assertIn('input63', map_library.catalog()['SwitchColorMap']['attributes'])
        graph = nodes.new()
        graph['nodes']['red'] = {'type': 'ConstantColorMap', 'parameters': {'color_value': [1, 0, 0]}}
        # As a graph was saved before: the first input under the unnumbered name.
        graph['nodes']['pick'] = {'type': 'SwitchColorMap', 'parameters': {'choice': 0}, 'inputs': {'input': 'red'}}
        graph['nodes']['surface']['inputs']['albedo'] = 'pick'
        lines = []
        nodes.emit({'node_graph': graph, 'color': [.5] * 3}, '/test', [0], lines, {})
        text = '\n'.join(lines)
        self.assertIn('["input0"] = bind(ConstantColorMap(', text)
        self.assertNotIn('["input"]', text)


if __name__ == '__main__':
    unittest.main()
