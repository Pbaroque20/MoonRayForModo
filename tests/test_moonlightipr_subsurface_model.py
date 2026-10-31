"""MoonLightIPR follows the subsurface model a native material chooses. No Modo."""
import sys
import types
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
sys.modules.setdefault('modo', types.ModuleType('modo'))
sys.modules.setdefault('lx', types.ModuleType('lx'))
from moonray_modo import material_settings, moonlightipr_materials


class SubsurfaceModel(unittest.TestCase):
    def surface(self, shader='DwaSkinMaterial', **parameters):
        return moonlightipr_materials.native_surface(shader, dict(scattering_radius=.4, **parameters), lambda *_: None)

    def test_a_chosen_random_walk_is_passed_on(self):
        surface = self.surface(bssrdf=2)
        self.assertEqual(surface['subsurface_model'], 2)
        self.assertEqual(material_settings.values(surface)['subsurface_model'], 2)

    def test_the_default_stays_normalized_diffusion(self):
        self.assertEqual(self.surface()['subsurface_model'], 0)


class KernelRules(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        self.kernel = (root / 'moonlightipr/src/device/kernel.cu').read_text(encoding='utf-8')
        self.scene = (root / 'kit/MoonRayForModo/python/moonray_modo/moonlightipr_scene.py').read_text(encoding='utf-8')
        self.loader = (root / 'moonlightipr/session/scene_loader.cpp').read_text(encoding='utf-8')

    def test_scattering_starts_from_what_diffuse_transmission_leaves(self):
        self.assertEqual(self.kernel.count('const float3 scatterColour = surface.albedo * surface.frontKeep;'), 2)
        self.assertNotIn('const float3 entered = surface.frontKeep', self.kernel)
        self.assertNotIn('throughput *= surface.frontKeep', self.kernel)

    def test_the_paths_limit_goes_from_the_scene_to_the_kernel(self):
        self.assertIn("int(settings['max_subsurface_per_path'])", self.scene)
        self.assertIn('renderer.setMaxSubsurface(maxSubsurface)', self.loader)
        self.assertIn('subsurfaces < params.maxSubsurface', self.kernel)
        self.assertEqual(self.kernel.count('++subsurfaces;'), 2)


if __name__ == '__main__':
    unittest.main()
