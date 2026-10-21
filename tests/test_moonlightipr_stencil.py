"""MoonLightIPR's Shader Tree stencils: a stencil layer goes to the GPU on a channel of its own, which takes the surface
away over any dissolve (the kernel's presence test), and a material row leaves it as it is."""
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_materials as materials


class Stencil(unittest.TestCase):
    def test_a_stencil_layer_has_its_own_channel(self):
        self.assertEqual(materials.CHANNELS['stencil'], 27)
        self.assertNotEqual(materials.CHANNELS['stencil'], materials.CHANNELS['dissolve'])

    def test_material_rows_leave_the_stencil_alone(self):
        self.assertIn('stencil', materials.UNSET_BY_ROWS)

    def test_a_stencil_row_is_packed_for_the_gpu(self):
        compiler = materials.Compiler()
        compiler.material({'color': [.5, .5, .5], 'roughness': .4, 'standard_material': True,
                           'layers': [{'kind': 'constant', 'effect': 'stencil', 'value': [1, 1, 1], 'opacity': 1.0, 'blend': 'normal',
                                       'invert': False, 'groups': []}]}, 'cut')
        channels = [struct.unpack_from('<I', row)[0] for row in compiler.layers]
        self.assertIn(27, channels)


if __name__ == '__main__':
    unittest.main()
