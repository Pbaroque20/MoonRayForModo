"""Modo's Weight Map Texture layer: the gradient it is, and how MoonRay is given it. No Modo."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import gradients, procedurals


def read(**values):
    defaults = dict(vmap='Cornea', bias=.5, gain=.5, value1=0.0, value2=1.0, alpha1=1.0, alpha2=1.0)
    defaults.update(values)
    colours = {'color1': values.get('color1', (0, 0, 0)), 'color2': values.get('color2', (1, 1, 1))}
    return (None, lambda layer, name, default=None: defaults.get(name, default), lambda layer, name, default=None: colours.get(name, default))


class CurveTests(unittest.TestCase):
    def test_default_bias_and_gain_leave_the_weight(self):
        for t in (0, .1, .25, .5, .75, 1):
            self.assertAlmostEqual(procedurals.weight_curve(t, .5, .5), t)

    def test_ends_stay_whatever_the_bias_and_gain(self):
        for bias, gain in ((.2, .8), (.8, .2), (0, 1), (1, 0)):
            self.assertAlmostEqual(procedurals.weight_curve(0, bias, gain), 0, places=6)
            self.assertAlmostEqual(procedurals.weight_curve(1, bias, gain), 1, places=6)

    def test_bias_moves_the_middle(self):
        self.assertGreater(procedurals.weight_curve(.5, .2, .5), .5)
        self.assertLess(procedurals.weight_curve(.5, .8, .5), .5)

    def test_as_modo_renders_it(self):
        # Modo's own render of Low 0.2, High 0.8, Bias 0.3, Gain 0.7 at these weights (probe_gui_weight_layer.py).
        for weight, modo in ((.1, .2693), (.25, .4233), (.4, .6187), (.5, .6836), (.6, .7231), (.75, .7627), (.9, .7876)):
            self.assertAlmostEqual(.2 + .6 * procedurals.weight_curve(weight, .3, .7), modo, delta=.006)

    def test_outside_clamps(self):
        self.assertEqual(procedurals.weight_curve(-1, .5, .5), 0)
        self.assertEqual(procedurals.weight_curve(2, .5, .5), 1)


class ReducedTests(unittest.TestCase):
    def test_no_more_than_moonray_keeps_and_both_ends(self):
        data = {'positions': [i / 256 for i in range(257)], 'colors': [[(i / 256) ** 2] * 3 for i in range(257)]}
        kept = gradients.reduced(data)
        self.assertLessEqual(len(kept['positions']), 10)
        self.assertEqual((kept['positions'][0], kept['positions'][-1]), (0, 1))
        self.assertEqual(kept['positions'], sorted(kept['positions']))

    def test_a_straight_line_needs_only_its_ends(self):
        data = {'positions': [i / 256 for i in range(257)], 'colors': [[i / 256] * 3 for i in range(257)]}
        self.assertEqual(len(gradients.reduced(data)['positions']), 2)

    def test_stays_near_a_curve_all_the_way_up(self):
        data = {'positions': [i / 256 for i in range(257)], 'colors': [[(i / 256) ** 2] * 3 for i in range(257)]}
        kept = gradients.reduced(data)
        for i in range(257):
            self.assertAlmostEqual(gradients.sample(kept, i / 256)[0], (i / 256) ** 2, delta=.01)

    def test_a_short_gradient_is_left_and_alpha_comes_with_it(self):
        short = {'positions': [0, 1], 'colors': [[0] * 3, [1] * 3]}
        self.assertIs(gradients.reduced(short), short)
        data = {'positions': [i / 256 for i in range(257)], 'colors': [[0] * 3] * 257, 'alpha': [(i / 256) ** 2 for i in range(257)]}
        kept = gradients.reduced(data)
        self.assertEqual(len(kept['alpha']), len(kept['positions']))
        self.assertGreater(len(kept['positions']), 2)


class GradientTests(unittest.TestCase):
    def test_a_value_goes_from_low_to_high(self):
        data = procedurals.vertex_map(*read(value1=.2, value2=.8), False)
        self.assertEqual((data['input'], data['vmap']), ('@vmap', 'Cornea'))
        self.assertEqual(data['colors'][0], [.2] * 3)
        self.assertAlmostEqual(data['colors'][-1][0], .8)
        self.assertAlmostEqual(data['colors'][128][0], .5)
        self.assertNotIn('alpha', data)

    def test_a_colour_goes_from_its_low_colour_to_its_high(self):
        data = procedurals.vertex_map(*read(color1=(1, 0, 0), color2=(0, 0, 1)), True)
        self.assertEqual(data['colors'][0], [1, 0, 0])
        self.assertEqual(data['colors'][-1], [0, 0, 1])

    def test_alpha_only_where_it_is_not_whole(self):
        data = procedurals.vertex_map(*read(alpha1=0.0), False)
        self.assertEqual((data['alpha'][0], data['alpha'][-1]), (0, 1))

    def test_moonray_reads_the_map_by_its_name(self):
        made = []

        def node(kind, attributes):
            made.append((kind, attributes))
            return kind + str(len(made))
        gradients.emit(procedurals.vertex_map(*read(), False), {}, node, lambda value: 'rgb')
        kinds = [kind for kind, _ in made]
        self.assertEqual(kinds[0], 'AttributeMap')
        self.assertEqual(kinds[-1], 'RampMap')
        self.assertEqual(made[0][1]['primitive_attribute_name'], '"Cornea"')
        self.assertEqual(made[0][1]['primitive_attribute_type'], '0')


class MoonLightIPRTests(unittest.TestCase):
    def test_a_weight_comes_as_coordinates_for_each_corner(self):
        from moonray_modo.moonlightipr_scene import with_weights
        mesh = {'faces': [[0, 1, 2], [2, 1, 3]], 'point_attributes': {'Cornea': {'kind': 'float', 'values': [[.1], [.2], [.3], [.4]]}}}
        available = {}
        with_weights(mesh, available, {'': 0, '@vmap:Cornea': 1})
        self.assertEqual(available, {'@vmap:Cornea': [(.1, 0.0), (.2, 0.0), (.3, 0.0), (.3, 0.0), (.2, 0.0), (.4, 0.0)]})

    def test_values_set_apart_on_corners_go_first(self):
        from moonray_modo.moonlightipr_scene import with_weights
        mesh = {'faces': [[0, 1, 2]], 'point_attributes': {'Cornea': {'kind': 'float', 'values': [[0], [0], [0]]}},
                'corner_attributes': {'Cornea': {'kind': 'float', 'values': [[.5], [.6], [.7]]}}}
        available = {}
        with_weights(mesh, available, {'@vmap:Cornea': 0})
        self.assertEqual(available['@vmap:Cornea'], [(.5, 0.0), (.6, 0.0), (.7, 0.0)])

    def test_a_mesh_without_the_map_or_a_colour_map_has_none(self):
        from moonray_modo.moonlightipr_scene import with_weights
        for mesh in ({'faces': [[0, 1, 2]]}, {'faces': [[0, 1, 2]], 'point_attributes': {'Cornea': {'kind': 'color', 'values': [[1, 1, 1]] * 3}}}):
            available = {}
            with_weights(mesh, available, {'@vmap:Cornea': 0})
            self.assertEqual(available, {})


if __name__ == '__main__':
    unittest.main()
