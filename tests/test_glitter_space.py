"""Glitter starts in object space, not MoonRay's reference space, which needs rest positions Modo's meshes do not carry
(without them MoonRay renders the surface black); a space that was set, and a MoonRay scene's own, are kept."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import node_defaults

GLITTERING = ('DwaBaseMaterial', 'DwaFabricMaterial', 'DwaMetalMaterial', 'DwaSkinMaterial', 'DwaSolidDielectricMaterial',
              'DwaToonMaterial', 'DwaVelvetMaterial_v2')


class GlitterSpace(unittest.TestCase):
    def test_every_material_with_glitter_starts_in_object_space(self):
        for shader in GLITTERING:
            self.assertEqual(node_defaults.started(shader, {})['glitter_space'], 4, shader)

    def test_a_space_that_was_set_is_kept(self):
        self.assertEqual(node_defaults.started('DwaBaseMaterial', {'glitter_space': 5})['glitter_space'], 5)

    def test_the_toon_material_keeps_its_other_starts(self):
        started = node_defaults.started('DwaToonMaterial', {})
        self.assertEqual((started['diffuse_model'], started['specular_model']), (1, 2))

    def test_a_moonray_scene_keeps_moonrays_reference_space(self):
        graph = {'nodes': {'a': {'type': 'DwaBaseMaterial', 'parameters': {}}}}
        node_defaults.keep_moonray_defaults(graph)
        self.assertEqual(graph['nodes']['a']['parameters']['glitter_space'], 5)


if __name__ == '__main__':
    unittest.main()
