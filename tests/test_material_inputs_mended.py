"""Materials made of others that MoonRay would crash on, mended before the scene is written, each change a notice."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import shader_library


def native(shader, **parameters):
    return {'native_shader': shader, 'native_parameters': parameters}


BASE = {'material': 'base'}
EMPTY = {'material': 'adjust'}
LIBRARY = {'base': native('DwaBaseMaterial'), 'adjust': native('DwaAdjustMaterial')}


def mend(material, library=LIBRARY):
    warnings = []
    materials, mended_library = shader_library.mend({'tag': material}, library, warnings, {'adjust': 'Empty Adjust'})
    return materials['tag'], mended_library, warnings


class Mended(unittest.TestCase):
    def test_a_layer_without_its_b_is_given_its_a(self):
        material, _, warnings = mend(native('DwaLayerMaterial', material_A=BASE))
        self.assertEqual(material['native_parameters']['material_B'], BASE)
        self.assertEqual(len(warnings), 1)

    def test_a_layer_without_its_a_renders_as_it_is(self):
        material, _, warnings = mend(native('DwaLayerMaterial', material_B=BASE))
        self.assertIsNone(material['native_parameters'].get('material_A'))
        self.assertEqual(warnings, [])

    def test_a_two_sided_material_is_given_the_side_it_has(self):
        material, _, _ = mend(native('DwaTwoSidedMaterial', back_material=BASE))
        self.assertEqual(material['native_parameters']['front_material'], BASE)

    def test_an_empty_input_is_left_out(self):
        material, _, warnings = mend(native('DwaMixMaterial', material0=EMPTY, material1=BASE))
        self.assertIsNone(material['native_parameters']['material0'])
        self.assertEqual(material['native_parameters']['material1'], BASE)
        self.assertIn('Empty Adjust', warnings[0])

    def test_emptiness_is_followed_down(self):
        library = dict(LIBRARY, wrap=native('DwaColorCorrectMaterial', input_material=EMPTY))
        material, mended_library, _ = mend(native('DwaLayerMaterial', material_A={'material': 'wrap'}, material_B=BASE), library)
        self.assertIsNone(material['native_parameters']['material_A'])
        self.assertIsNone(mended_library['wrap']['native_parameters']['input_material'])

    def test_a_material_assigned_with_nothing_plugged_in_is_plain_grey(self):
        material, _, warnings = mend(native('DwaTwoSidedMaterial'))
        self.assertEqual(material['native_shader'], 'DwaBaseMaterial')
        self.assertEqual(len(warnings), 1)

    def test_a_whole_material_is_left_alone(self):
        given = native('DwaLayerMaterial', material_A=BASE, material_B=BASE, mask=0.5)
        material, mended_library, warnings = mend(given)
        self.assertEqual(material, given)
        self.assertEqual(mended_library, LIBRARY)
        self.assertEqual(warnings, [])
        self.assertIsNot(material, given)

    def test_a_node_graph_input_counts_as_plugged_in_and_is_given_to_its_pair(self):
        graph = {'nodes': {'a': {'type': 'DwaBaseMaterial', 'parameters': {}, 'inputs': {}},
                           'root': {'type': 'DwaTwoSidedMaterial', 'parameters': {}, 'inputs': {'front_material': 'a'}}},
                 'root': 'root'}
        material, _, warnings = mend(dict(native('DwaTwoSidedMaterial'), node_graph=graph))
        self.assertEqual(material['native_shader'], 'DwaTwoSidedMaterial')
        self.assertEqual(material['node_graph']['nodes']['root']['inputs'], {'front_material': 'a', 'back_material': 'a'})
        self.assertEqual(len(warnings), 1)
        self.assertEqual(graph['nodes']['root']['inputs'], {'front_material': 'a'})


if __name__ == '__main__':
    unittest.main()
