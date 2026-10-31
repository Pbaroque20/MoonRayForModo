"""The graph editor's colour numbers against Modo's form, and where glitter's flakes start. No Modo."""
import sys
import types
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
sys.modules.setdefault('modo', types.ModuleType('modo'))
from moonray_modo import node_defaults, parameter_state, shader_library


class Colours(unittest.TestCase):
    def test_numbers_are_the_ones_modos_form_shows_for_the_same_colour(self):
        # A material of metaltest.lxo: kept, and what Modo's form showed for it.
        for kept, shown in ((.604, .8), (.357, .63), (.071, .3), (1.0, 1.0), (.698, .85), (.396, .66)):
            self.assertAlmostEqual(parameter_state.shown_colour(kept), shown, delta=.006)

    def test_a_number_goes_there_and_back(self):
        for kept in (0.0, .001, .0031308, .04, .18, .5, 1.0, 2.5):
            self.assertAlmostEqual(parameter_state.kept_colour(parameter_state.shown_colour(kept)), kept, places=6)

    def test_below_zero_is_left_as_it_is(self):
        self.assertEqual(parameter_state.shown_colour(-.5), -.5)
        self.assertEqual(parameter_state.kept_colour(-.5), -.5)


class Flakes(unittest.TestCase):
    def emitted(self, shader='DwaMetalMaterial', **parameters):
        lines = []
        shader_library.emit({'native_shader': shader, 'native_parameters': parameters, 'color': [.5, .5, .5]}, '/m', [0], lines, {})
        return '\n'.join(lines)

    def test_glitter_on_starts_with_flakes_of_centimetres(self):
        text = self.emitted(show_glitter=True)
        self.assertIn('"glitter_size_A"] = 0.03', text)
        self.assertIn('"glitter_size_B"] = 0.03', text)

    def test_a_size_that_was_set_is_kept(self):
        self.assertIn('"glitter_size_A"] = 2', self.emitted(show_glitter=True, glitter_size_A=2.0))

    def test_nothing_is_written_with_glitter_off(self):
        self.assertNotIn('glitter_size', self.emitted())
        self.assertNotIn('glitter_size', self.emitted(show_glitter=False))

    def test_the_form_and_the_graph_read_the_same_start(self):
        spec = shader_library.catalog()['DwaMetalMaterial']['attributes']['glitter_size_A']
        self.assertEqual(node_defaults.start('DwaMetalMaterial', 'glitter_size_A', spec), .03)

    def test_a_graph_from_a_moonray_scene_keeps_moonrays_size(self):
        graph = {'nodes': {'m': {'type': 'DwaMetalMaterial', 'parameters': {'show_glitter': True}}}}
        node_defaults.keep_moonray_defaults(graph)
        self.assertEqual(graph['nodes']['m']['parameters']['glitter_size_A'], 1.0)


if __name__ == '__main__':
    unittest.main()
