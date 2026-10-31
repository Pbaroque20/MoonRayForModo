"""A final EXR's channels and parts, and glitter's rest positions: what the scene writer writes. No Modo."""
import sys
import types
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
sys.modules.setdefault('modo', types.ModuleType('modo'))
from moonray_modo import composite_output, options, outputs, reference_points, shader_library


class Names(unittest.TestCase):
    def test_alpha_and_depth_have_the_names_compositors_look_for(self):
        self.assertEqual(options.AOVS['alpha'][2], 'A')
        self.assertEqual(options.AOVS['depth'][2], 'depth.Z')

    def test_the_compositor_finds_them(self):
        names = ['R', 'G', 'B', 'A', 'depth.Z']
        self.assertEqual(composite_output.selection('alpha', names), 'R=A,G=A,B=A')
        self.assertEqual(composite_output.selection('depth', names), 'R=depth.Z,G=depth.Z,B=depth.Z')
        self.assertEqual(composite_output.selection('beauty', names), 'R,G,B')


class Parts(unittest.TestCase):
    def test_each_output_has_its_own_part_with_the_beauty_first(self):
        written = outputs.in_parts([('diffuse', {'result': 8}, 'diffuse'), ('beauty', {'result': 0}, ''), ('alpha', {'result': 1}, 'A'),
                                    ('matte', {'result': 13}, 'matte'), ('mine', {'result': 8, 'file_part': 'lights'}, 'mine')])
        parts = {name: attributes['file_part'] for name, attributes, _ in written}
        self.assertEqual(parts, {'diffuse': 'diffuse', 'beauty': 'rgba', 'alpha': 'rgba', 'matte': 'rgba', 'mine': 'lights'})
        self.assertEqual(written[0][1]['file_part'], 'rgba')

    def test_which_part_holds_a_buffer(self):
        parts = [['R', 'G', 'B', 'A'], ['depth.Z'], ['diffuse.R', 'diffuse.G', 'diffuse.B']]
        self.assertEqual(composite_output.part_of('beauty', parts), 0)
        self.assertEqual(composite_output.part_of('depth', parts), 1)
        self.assertEqual(composite_output.part_of('diffuse', parts), 2)
        self.assertIsNone(composite_output.part_of('normal', parts))


class Glitter(unittest.TestCase):
    def emitted(self, **parameters):
        lines = []
        shader_library.emit({'native_shader': 'DwaMetalMaterial', 'native_parameters': parameters, 'color': [.5, .5, .5]}, '/m', [0], lines, {})
        return '\n'.join(lines)

    def test_glitter_turned_off_is_left_out_not_false(self):
        self.assertNotIn('show_glitter', self.emitted(show_glitter=False))
        self.assertIn('"show_glitter"] = true', self.emitted(show_glitter=True))

    def test_a_mesh_read_without_rest_positions_gets_its_points(self):
        mesh = {'vertices': [[0, 0, 0]], 'point_attributes': {'weight': {'kind': 'float', 'values': [1]}}}
        made = reference_points.with_rest(mesh)
        self.assertEqual(made['point_attributes'][reference_points.NAME]['values'], [[0, 0, 0]])
        self.assertIn('weight', made['point_attributes'])
        self.assertNotIn(reference_points.NAME, mesh['point_attributes'])

    def test_rest_positions_it_has_are_kept(self):
        rest = {'kind': 'vec3', 'values': [[9, 9, 9]]}
        mesh = {'vertices': [[0, 0, 0]], 'point_attributes': {reference_points.NAME: rest}}
        self.assertIs(reference_points.with_rest(mesh), mesh)

    def test_only_glitter_on_in_reference_space_asks(self):
        wanted = lambda **p: reference_points.wanted({'m': {'native_shader': 'DwaMetalMaterial', 'native_parameters': p}})
        self.assertTrue(wanted(show_glitter=True))
        self.assertFalse(wanted(show_glitter=True, glitter_space=4))
        self.assertFalse(wanted(show_glitter=False))


if __name__ == '__main__':
    unittest.main()
