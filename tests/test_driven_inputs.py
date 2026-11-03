"""An input wired in the graph editor is the graph's: the Properties panel greys it, and does not cut the wire by setting a
value (material_override.driven_inputs, read by every material control's basic_Enable)."""
import json
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import material_override


def tag(inputs, overrides=()):
    graph = {'version': 1, 'root': 'surface', 'overrides': list(overrides), 'nodes': {
        'surface': {'type': 'DwaBaseMaterial', 'parameters': {}, 'inputs': inputs},
        'rough': {'type': 'ImageMap', 'parameters': {}, 'inputs': {}}}}
    return json.dumps({'moonshine_override': True, 'node_graph': graph})


class Driven(unittest.TestCase):
    def test_a_wired_input_names_its_node(self):
        self.assertEqual(material_override.driven_inputs(tag({'roughness': 'rough'})), {'roughness': 'ImageMap'})

    def test_nothing_wired_and_no_graph(self):
        self.assertEqual(material_override.driven_inputs(tag({})), {})
        self.assertEqual(material_override.driven_inputs(json.dumps({'native_shader': 'DwaBaseMaterial'})), {})
        self.assertEqual(material_override.driven_inputs(''), {})

    def test_an_override_that_cuts_the_wire_frees_the_input(self):
        cut = [{'name': 'Layer', 'node': 'surface', 'inputs': {'roughness': None}}]
        self.assertEqual(material_override.driven_inputs(tag({'roughness': 'rough'}, cut)), {})

    def test_the_commands_grey_and_refuse(self):
        forms = (ROOT / 'kit/MoonRayForModo/lxserv/moonray_material_forms.py').read_text(encoding='utf-8')
        self.assertEqual(forms.count('return bool(items) and not driven(items,'), 3)
        self.assertEqual(forms.count('if found:refuse(found,'), 3)
        older = (ROOT / 'kit/MoonRayForModo/lxserv/moonray_material_properties.py').read_text(encoding='utf-8')
        self.assertIn('not material_override.driver(item,key)', older)


if __name__ == '__main__':
    unittest.main()
