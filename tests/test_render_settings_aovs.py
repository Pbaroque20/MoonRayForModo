"""Render Settings' AOV sections: XPU and XPU2 Outputs (AOVs), which MoonRay XPU and XPU2 share, and MoonLightIPR Outputs
(AOVs). A tick turns a buffer on: rendered (MoonRay's previews, outputs.rendered), listed among the preview window's
buffers (panel._limit_buffers) and written to the EXR; Alpha alone is on in a new scene, in both."""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))

from moonray_modo import moonlightipr_aovs, options, outputs, scene_settings  # noqa: E402


def group(name):
    return next(entries for label, _, entries in scene_settings.GROUPS if label == name)


class Sections(unittest.TestCase):
    def test_xpu_and_xpu2_share_one_section(self):
        entries = group('XPU and XPU2 Outputs (AOVs)')
        self.assertEqual([e['member'] for e in entries], list(options.AOVS))
        self.assertTrue(all(e['path'] == ('aovs',) for e in entries))
        self.assertIn('XPU and XPU2', next(e for e in entries if e['member'] == 'depth')['tip'])

    def test_moonlightipr_has_its_own_section_with_every_aov_it_makes(self):
        entries = group('MoonLightIPR Outputs (AOVs)')
        self.assertEqual(sorted(e['member'] for e in entries), sorted(moonlightipr_aovs.AOVS))
        self.assertTrue(all(e['path'] == ('moonlightipr_aovs',) for e in entries))
        self.assertEqual(len({e['key'] for e in entries}), len(entries))
        self.assertIn('MoonLightIPR Outputs (AOVs)', scene_settings.SHEET_KEYS)

    def test_alpha_alone_is_on_in_a_new_scene(self):
        settings = scene_settings.complete({})
        self.assertEqual(settings['aovs'], ['alpha'])
        self.assertEqual(settings['moonlightipr_aovs'], ['alpha'])
        self.assertEqual(moonlightipr_aovs.listed(settings), {'alpha'})

    def test_the_form_has_both_sections(self):
        form = (ROOT / 'kit/MoonRayForModo/render_settings.cfg').read_text(encoding='utf-8')
        self.assertIn('XPU and XPU2 Outputs (AOVs)', form)
        self.assertIn('MoonLightIPR Outputs (AOVs)', form)
        self.assertIn('moonray.render.moonlightipr_aov_alpha', form)
        self.assertNotIn('>Outputs (AOVs)<', form)


class Rendered(unittest.TestCase):
    def preview(self, **scene):
        with mock.patch('moonray_modo.native.pbr_validity', return_value=False):
            return set(outputs.preview(dict(scene)))

    def test_only_the_ticked_aovs_are_rendered(self):
        # Every one of MoonRay's AOVs was rendered for each preview, whatever was ticked.
        made = self.preview(aovs=['depth'])
        self.assertEqual(made & set(options.AOVS), {'depth'})
        self.assertIn('beauty', made)

    def test_alpha_brings_the_environment_background_for_straight_alpha_saves(self):
        self.assertEqual(self.preview(aovs=['alpha']) & set(options.AOVS), {'alpha', 'environment_background'})

    def test_the_buffer_looked_at_and_the_compositors_are_rendered_too(self):
        graph = {'nodes': {'n': {'type': 'input', 'parameters': {'buffer': 'normal'}, 'inputs': {}, 'position': [0, 0]}}, 'output': 'n'}
        with mock.patch('moonray_modo.compositor.buffers', return_value=['normal']):
            made = self.preview(aovs=[], preview_buffer='uv', compositor=graph)
        self.assertEqual(made & set(options.AOVS), {'uv', 'normal'})

    def test_the_list_offers_the_ticked_ones(self):
        self.assertEqual(outputs.listed({'aovs': ['depth']}) & set(options.AOVS), {'depth', 'pbr_validity'})


if __name__ == '__main__':
    unittest.main()
