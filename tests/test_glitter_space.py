"""Glitter starts in MoonRay's own reference space, with each mesh's rest positions sent for it (reference_points); a
space that was set is kept."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import node_defaults, reference_points

GLITTERING = ('DwaBaseMaterial', 'DwaFabricMaterial', 'DwaMetalMaterial', 'DwaSkinMaterial', 'DwaSolidDielectricMaterial',
              'DwaToonMaterial', 'DwaVelvetMaterial_v2')


class GlitterSpace(unittest.TestCase):
    def test_glitter_is_left_to_moonrays_reference_space(self):
        for shader in GLITTERING:
            self.assertNotIn('glitter_space', node_defaults.started(shader, {}), shader)
            # Shown, it asks for rest positions.
            self.assertTrue(reference_points.in_reference_space(shader, node_defaults.started(shader, {'show_glitter': True})), shader)

    def test_a_space_that_was_set_is_kept(self):
        self.assertEqual(node_defaults.started('DwaBaseMaterial', {'glitter_space': 4})['glitter_space'], 4)
        self.assertFalse(reference_points.in_reference_space('DwaBaseMaterial', {'show_glitter': True, 'glitter_space': 4}))

    def test_the_toon_material_keeps_its_other_starts(self):
        started = node_defaults.started('DwaToonMaterial', {})
        self.assertEqual((started['diffuse_model'], started['specular_model']), (1, 2))


if __name__ == '__main__':
    unittest.main()
