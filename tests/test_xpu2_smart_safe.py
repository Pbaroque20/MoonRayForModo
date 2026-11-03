"""Smart Render and Safe Denoising are MoonRay's: off only where XPU2 renders the preview, that is with XPU2 chosen in the
preferences and the scene's Rendering Mode XPU or Auto. A change of that choice makes the Render item's form look again."""
import sys
import unittest
from pathlib import Path
from unittest import mock
ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
from moonray_modo import native


class Renders(unittest.TestCase):
    def test_xpu2_renders_only_in_xpu_or_auto_with_it_chosen(self):
        with mock.patch.object(native, 'xpu2', return_value=True):
            self.assertTrue(native.xpu2_renders('xpu'))
            self.assertTrue(native.xpu2_renders('auto'))
            self.assertTrue(native.xpu2_renders(None))
            self.assertFalse(native.xpu2_renders('vectorized'))
            self.assertFalse(native.xpu2_renders('scalar'))
        with mock.patch.object(native, 'xpu2', return_value=False):
            self.assertFalse(native.xpu2_renders('xpu'))

    def test_the_places_that_grey_or_skip_them_ask_by_mode(self):
        form = (KIT / 'lxserv/moonray_render_settings.py').read_text(encoding='utf-8')
        self.assertIn('if native.xpu2_renders(mode):return False', form)
        render = (KIT / 'python/moonray_modo/render.py').read_text(encoding='utf-8')
        self.assertIn("not native.xpu2_renders(self.active['snapshot'].get('execution_mode','auto'))", render)
        panel = (KIT / 'python/moonray_modo/panel.py').read_text(encoding='utf-8')
        self.assertNotIn('if native.xpu2():smart.setEnabled', panel)
        self.assertNotIn('if native.xpu2():safe.setEnabled', panel)

    def test_smart_render_brings_optix_on_an_nvidia_card_and_oidn_without(self):
        from moonray_modo import hardware
        with mock.patch.object(hardware, 'gpu', return_value='RTX 3090'):
            self.assertEqual(hardware.denoiser(), 'optix')
        with mock.patch.object(hardware, 'gpu', return_value=''):
            self.assertEqual(hardware.denoiser(), 'oidn_cpu')
        panel = (KIT / 'python/moonray_modo/panel.py').read_text(encoding='utf-8')
        self.assertIn("stored['engine']=denoiser()", panel)

    def test_choosing_the_renderer_refreshes_the_render_form(self):
        commands = (KIT / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8')
        self.assertIn("choice('xpu2/renderer',(('xpu','MoonRay XPU'),('xpu2','XPU2')),render_settings_changed)", commands)


if __name__ == '__main__':
    unittest.main()
