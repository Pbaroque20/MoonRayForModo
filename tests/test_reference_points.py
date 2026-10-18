"""Rest positions (ref_P) are asked for only where glitter is in reference space, and are written as MoonRay reads them."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import rdla, reference_points


def native(**parameters):
    return {'native_shader': 'DwaBaseMaterial', 'native_parameters': parameters}


class Wanted(unittest.TestCase):
    def test_only_glitter_in_reference_space_asks(self):
        self.assertFalse(reference_points.wanted({'': native()}))
        self.assertFalse(reference_points.wanted({'': native(show_glitter=True, glitter_space=4)}))
        self.assertTrue(reference_points.wanted({'': native(show_glitter=True, glitter_space=5)}))
        # Glitter's space left unset is MoonRay's own, reference space.
        self.assertTrue(reference_points.wanted({'': native(show_glitter=True)}))
        self.assertFalse(reference_points.wanted({'': native(glitter_space=5)}))

    def test_a_graph_node_or_a_layer_of_the_stack_asks_too(self):
        graph = {'nodes': {'n': {'type': 'DwaMetalMaterial', 'parameters': {'show_glitter': True, 'glitter_space': 5}}}}
        self.assertTrue(reference_points.wanted({'a': {'node_graph': graph}}))
        self.assertTrue(reference_points.wanted({'a': {'material_stack': [native(show_glitter=True)]}}))
        self.assertFalse(reference_points.wanted({'a': {'native_shader': 'DwaEmissiveMaterial', 'native_parameters': {'show_glitter': True}}}))


class Written(unittest.TestCase):
    def test_rest_positions_are_a_vector_at_each_point_named_ref_P(self):
        rest = [[0, 0, 0], [1, 0, 0], [0, 1, 0]]
        scene = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 4, 1], 'focal_mm': 50, 'film_mm': 36},
                 'materials': {'': {'color': [.5, .5, .5]}},
                 'meshes': [{'name': 'T', 'identity': 't', 'vertices': rest, 'faces': [[0, 1, 2]], 'matrix': rdla.IDENTITY,
                             'point_attributes': {'ref_P': {'kind': 'vec3', 'values': rest}}}]}
        text = rdla.scene_text(scene)
        self.assertIn('["vec3f_key"] = "ref_P"', text)
        block = text[text.index('["vec3f_key"] = "ref_P"'):]
        self.assertIn('["rate"] = 4', block[:200])
        self.assertIn('["vec3f_values_0"]', block[:300])


if __name__ == '__main__':
    unittest.main()
