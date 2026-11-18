"""A material over others in MoonLightIPR covers their bumps and normal maps, as Modo renders it and MoonRay's graph does
(moonlightipr_materials: a material row puts bump and normal back to flat where a row below set them). A report: a
material in a group over the Shader Tree's others showed their bump maps through it. Run outside Modo, no GPU needed."""
import struct
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo.moonlightipr_materials import CHANNELS, Compiler  # noqa: E402

ROW = struct.Struct('<3Ii1I19fI36f')


def row(name, colour, opacity=1.0, layers=()):
    return {'name': name, 'base_layer_id': name, 'shader': 'DwaBaseMaterial', 'color': colour, 'raw_color': colour,
            'roughness': .5, 'layer_opacity': opacity, 'layer_blend': 'normal', 'material_groups': [], 'layers': list(layers)}


def rows(stack):
    """Each GPU row as (channel, value, opacity), bottom to top."""
    compiler = Compiler()
    compiler.material({'material_stack': stack}, 'stack')
    return [(fields[0], tuple(round(v, 6) for v in fields[5:8]), round(fields[8], 6)) for fields in map(ROW.unpack, compiler.layers)]


class CoversBumps(unittest.TestCase):
    def test_a_material_over_a_bump_flattens_it(self):
        bump = {'kind': 'constant', 'effect': 'bump', 'value': [.7, .7, .7], 'groups': []}
        found = rows([row('under', [1, 0, 0], layers=[bump]), row('over', [0, 0, 1], .5)])
        bumps = [r for r in found if r[0] == CHANNELS['bump']]
        self.assertEqual(bumps[0][1], (.7, .7, .7))
        # Over it, the upper material's: flat, at that material's opacity.
        self.assertEqual(bumps[-1], (CHANNELS['bump'], (0.0, 0.0, 0.0), .5))

    def test_a_material_over_a_normal_map_flattens_it(self):
        normal = {'kind': 'constant', 'effect': 'normal', 'value': [.2, .8, .9], 'groups': []}
        found = rows([row('under', [1, 0, 0], layers=[normal]), row('over', [0, 0, 1])])
        normals = [r for r in found if r[0] == CHANNELS['normal']]
        self.assertEqual(normals[-1], (CHANNELS['normal'], (.5, .5, 1.0), 1.0))

    def test_a_bump_over_its_material_is_kept(self):
        bump = {'kind': 'constant', 'effect': 'bump', 'value': [.7, .7, .7], 'groups': []}
        found = rows([row('under', [1, 0, 0]), row('over', [0, 0, 1], layers=[bump])])
        self.assertEqual([r for r in found if r[0] == CHANNELS['bump']], [(CHANNELS['bump'], (.7, .7, .7), 1.0)])

    def test_no_rows_where_nothing_below_bumped(self):
        self.assertEqual(rows([row('under', [1, 0, 0]), row('over', [0, 0, 1], .5)]), [])


if __name__ == '__main__':
    unittest.main()
