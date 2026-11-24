"""A matte shadow catcher (a MoonRay Object's Make as Shadow Catcher) shows what the camera would see past it, darkened
by the shadows on it, rather than black: MoonRay (tools/port_shadow_catcher.py), XPU2 and MoonLightIPR alike."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
sys.path.insert(0, str(ROOT / 'tools'))


def text(path):
    return (ROOT / path).read_text(encoding='utf-8')


class ShadowCatcherBackgroundTests(unittest.TestCase):
    def test_object_catcher_is_a_matte(self):
        from moonray_modo import backplate, native
        held = native.shadow_catcher_runtime
        native.shadow_catcher_runtime = lambda *a, **k: True
        try:
            scene = {'meshes': [{'name': 'Ground', 'identity': 'g', 'vertices': [[0, 0, 0], [1, 0, 0], [1, 0, 1]], 'faces': [[0, 1, 2]],
                                 'material': 'm', 'geometry_settings': {'shadow_catcher': True, 'shadow_strength': 0.5}}]}
            backplate.catchers(scene, [])
        finally:
            native.shadow_catcher_runtime = held
        material = scene['materials'][scene['meshes'][0]['material']]
        self.assertEqual(material['shadow_catcher'], {'strength': 0.5, 'matte': True})

    def test_moonray_port_shows_the_background(self):
        import port_shadow_catcher as port
        self.assertIn('modoCatcherBackground(', port.BACKGROUND_HELPER)
        self.assertIn('LPE_EVENT_SCATTERING_TYPE_STRAIGHT', port.BACKGROUND_HELPER)
        self.assertIn('modoCatcherLpe(pbrTls, rays[slot], bgLpe', port.SHARE_HELPERS)
        self.assertIn('modoMatteCatcherAt(isect)', port.KEEP_NEW)
        # Scalar: the camera-visible lights past the hit, through the camera's straight event in the outputs.
        self.assertIn('intersectVisibleLight(modoPast', port.PRIMARY_NEW)
        self.assertIn('straightEventTransition', port.PRIMARY_NEW)
        # The sources built are those the port writes (where they are checked out).
        for name, block in (('PathIntegratorBundled.ispc', port.BACKGROUND_HELPER), ('PathIntegratorBundled.ispc', port.CATCHER_BLOCK),
                            ('PathIntegratorMultiSampler.ispc', port.SHARE_HELPERS), ('PathIntegratorMultiSampler.ispc', port.KEEP_NEW),
                            ('PathIntegrator.cc', port.PRIMARY_NEW)):
            source = port.RENDERING / 'pbr/integrator' / name
            if source.exists():
                self.assertIn(block, source.read_bytes().decode('utf-8').replace('\r\n', '\n'), name)

    def test_patch_exported(self):
        patch = text('patches/native-windows/moonray.patch')
        self.assertTrue('modoCatcherBackground' in patch and 'modoMatteCatcherAt' in patch,
                        'moonray.patch is to be exported again (tools/export_native_patches.py)')

    def test_xpu2_and_moonlightipr_show_the_background(self):
        integrator = text('xpu2/interactive/async_integrator.h')
        self.assertIn('catcherShown = pv.T * visibleLightRadiance(c, root, backend, hit.point', integrator)
        self.assertIn('aov::lpeStraight(at, pv.lpe), aov::LpeLight', integrator)
        self.assertIn('lobeLpe[0] = catcherLpe;', integrator)
        kernel = text('moonlightipr/src/device/kernel.cu')
        self.assertIn('ML_INLINE float3 catcherBackground(', kernel)
        self.assertIn('behind = catcherBackground(hit.p, direction, seenLight);', kernel)


if __name__ == '__main__':
    unittest.main()
