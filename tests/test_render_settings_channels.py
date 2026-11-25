"""The render settings as channels of the Render item (moonray_modo/render_channels.py), so Modo's Channels viewport
lists them, filters them, keys and links them: which settings are channels, their names and defaults, the channels'
values read over the tag (overlay), and what is set on the channels for a tag (wanted, changed_channels): a scene
opened with only the tag, and each edit through the form."""
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))

from moonray_modo import render_channels, scene_settings  # noqa: E402


def entry(key):
    return next(e for e in scene_settings.FIELDS if e['key'] == key)


class Plain(unittest.TestCase):
    """complete() without this machine's remembered display or preferences."""
    def setUp(self):
        from moonray_modo import display_memory  # noqa: F401
        patches = [mock.patch('moonray_modo.display_memory.remembered', return_value={})]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def complete(self, stored):
        return scene_settings.complete(stored)


class Which(Plain):
    def test_every_setting_of_the_form_is_a_channel_but_buttons_and_cameras(self):
        keys = {e['key'] for e in render_channels.entries()}
        for field in scene_settings.FIELDS:
            if field['kind'] in ('button', 'command') or field['key'] in scene_settings.NOT_IN_FORM:
                self.assertNotIn(field['key'], keys)
            else:
                self.assertIn(field['key'], keys)
        self.assertNotIn('camera', keys)
        self.assertNotIn('dicing_camera', keys)
        # Lists and records stay in the tag alone.
        paths = {e['path'][0] for e in render_channels.entries()}
        for kept in ('custom_aovs_expressions', 'production', 'camera_sequence', 'compositor', 'scene_variables'):
            self.assertNotIn(kept, paths - {'custom_aovs'})

    def test_channel_kinds(self):
        self.assertEqual(render_channels.kind(entry('samples')), 'integer')
        self.assertEqual(render_channels.kind(entry('sample_clamping_value')), 'float')
        self.assertEqual(render_channels.kind(entry('denoiser')), 'integer')
        self.assertEqual(render_channels.kind(entry('denoise_preview')), 'boolean')
        self.assertEqual(render_channels.kind(entry('aov_alpha')), 'boolean')
        self.assertEqual(render_channels.kind(entry('background_color')), 'color')
        self.assertEqual(render_channels.kind(entry('lut')), 'string')
        self.assertEqual(render_channels.channel(entry('samples')), 'mr_samples')

    def test_names_are_unique_readable_and_found_by_clamp(self):
        names = render_channels.user_names()
        self.assertEqual(len(set(names.values())), len(names))
        self.assertEqual(set(names), {render_channels.channel(e) for e in render_channels.entries()})
        clamps = sorted(v for v in names.values() if 'clamp' in v.lower())
        self.assertIn('Noise: Sample Clamp', clamps)
        self.assertIn('MoonLightIPR: Sample Clamp', clamps)
        self.assertEqual(names['mr_max_depth'], 'Bounces: Total')
        self.assertEqual(names['mr_region_enabled'], 'Render Region')
        self.assertTrue(all(v.isascii() for v in names.values()))

    def test_a_choice_says_its_numbers_in_its_tip(self):
        tip = render_channels.tips()['mr_denoiser']
        self.assertIn('0 Off', tip)
        self.assertIn('1 NVIDIA OptiX (GPU)', tip)

    def test_defaults_are_what_the_form_shows_for_a_new_scene(self):
        marks = render_channels.defaults()
        held = self.complete({})
        for e in render_channels.entries():
            if e['path'][0] == 'display':
                continue
            self.assertEqual(marks[e['key']], scene_settings.get(held, e), e['key'])
        self.assertEqual(marks['samples'], 4)
        self.assertEqual(marks['aov_alpha'], True)
        self.assertEqual(marks['aov_crypto_object'], True)
        self.assertEqual(marks['view'], 0)


class Overlay(Plain):
    def test_channels_at_defaults_leave_the_tag_as_it_is(self):
        stored = {'samples': 9, 'light_multiplier': 2.0}
        values = dict(render_channels.defaults(), samples=9, light_multiplier=2.0)
        self.assertIs(render_channels.overlay(stored, values), stored)

    def test_a_channel_changed_wins_over_the_tag(self):
        stored = {'samples': 9}
        values = dict(render_channels.defaults(), samples=12, sample_clamping_value=3.5, denoiser=1, background_color=[1.0, 0.0, 0.0],
                      region_left=25.0, aov_depth=True, lut='C:/luts/a.cube')
        result = self.complete(render_channels.overlay(stored, values))
        self.assertEqual(result['samples'], 12)
        self.assertEqual(result['render']['sample_clamping_value'], 3.5)
        self.assertEqual(result['denoising']['engine'], 'optix')
        self.assertEqual(result['background']['color'], '#ff0000')
        self.assertAlmostEqual(result['region'][0], 0.25)
        self.assertIn('depth', result['aovs'])
        self.assertEqual(result['display']['lut'], 'C:/luts/a.cube')
        self.assertEqual(stored, {'samples': 9})

    def test_a_channel_set_back_to_its_default_wins_where_the_tag_set_it(self):
        stored = {'samples': 9}
        values = dict(render_channels.defaults())
        self.assertEqual(self.complete(render_channels.overlay(stored, values))['samples'], 4)

    def test_settings_whose_default_follows_stay_following(self):
        # MoonLightIPR's clamp is MoonRay's until set: its channel at the default reads as not set.
        stored = {'render': {'sample_clamping_value': 5.0}}
        values = dict(render_channels.defaults(), sample_clamping_value=5.0)
        self.assertEqual(self.complete(render_channels.overlay(stored, values))['moonlightipr']['sample_clamp'], 5.0)
        values['moonlightipr_sample_clamp'] = 2.0
        self.assertEqual(self.complete(render_channels.overlay(stored, values))['moonlightipr']['sample_clamp'], 2.0)
        # The display's view, as last chosen on this machine, until the scene chooses it.
        with mock.patch('moonray_modo.display_memory.remembered', return_value={'view': 'aces'}):
            self.assertEqual(self.complete(render_channels.overlay({}, dict(render_channels.defaults())))['display']['view'], 'aces')

    def test_empty_text_channels_read_as_not_set(self):
        # Modo's text channels start empty: an OCIO source left so keeps the display's own.
        values = dict(render_channels.defaults(), ocio_source='', ocio_display='', ocio_view='', lut='')
        self.assertEqual(self.complete(render_channels.overlay({}, values))['display']['source'], 'Linear Rec.709 (sRGB)')
        # Where the tag set it, an emptied channel empties it.
        stored = {'display': {'lut': 'C:/a.cube'}}
        self.assertEqual(self.complete(render_channels.overlay(stored, dict(values, lut='')))['display']['lut'], '')

    def test_limits_and_bad_values(self):
        values = dict(render_channels.defaults(), samples=1000, denoiser=99, min_adaptive_samples=50, max_adaptive_samples=10)
        result = self.complete(render_channels.overlay({}, values))
        self.assertEqual(result['samples'], 64)
        self.assertEqual(result['denoising']['engine'], 'off')
        # Adaptive sampling's fewest above its most: the most raised to it, the other render settings kept.
        self.assertEqual(result['render']['min_adaptive_samples'], 50)
        self.assertEqual(result['render']['max_adaptive_samples'], 50)

    def test_smart_render_and_safe_denoising_stay_one_or_the_other(self):
        values = dict(render_channels.defaults(), smart_render=1)
        result = self.complete(render_channels.overlay({'denoising': {'safe': True}}, values))
        self.assertEqual(result['denoising']['smart'], 'draft')
        self.assertFalse(result['denoising']['safe'])

    def test_cryptomatte_ticks(self):
        values = dict(render_channels.defaults(), aov_crypto_object=False, aov_crypto_material=True)
        result = self.complete(render_channels.overlay({}, values))
        kinds = [(v['kind'], v.get('category')) for v in result['custom_aovs']]
        self.assertNotIn(('cryptomatte', 'object'), kinds)
        self.assertIn(('cryptomatte', 'material'), kinds)


class Written(Plain):
    def test_an_old_scene_moves_what_its_tag_set(self):
        stored = {'samples': 9, 'render': {'max_depth': 7}, 'denoising': {'engine': 'optix'}, 'background': {'color': '#336699'}}
        wanted = render_channels.wanted(stored)
        self.assertEqual(wanted['samples'], 9)
        self.assertEqual(wanted['max_depth'], 7)
        self.assertEqual(wanted['denoiser'], 1)
        self.assertEqual(wanted['background_color'], scene_settings.hex_to_rgb('#336699'))
        # What it has not set is left at the channels' defaults, still not set.
        self.assertNotIn('denoise_preview', wanted)
        self.assertNotIn('view', wanted)
        self.assertNotIn('moonlightipr_sample_clamp', wanted)
        # And read back, the scene is as it was.
        values = dict(render_channels.defaults(), **wanted)
        self.assertEqual(self.complete(render_channels.overlay(stored, values)), self.complete(stored))

    def test_a_form_edit_sets_only_its_channel(self):
        stored = {'samples': 9}
        current = dict(render_channels.defaults(), samples=9)
        scene_settings.put(stored, entry('light_multiplier'), 3.0)
        self.assertEqual(render_channels.changed_channels(current, stored), {'light_multiplier': 3.0})

    def test_a_form_edit_over_a_channel_edit(self):
        # The channel was changed in the Channels viewport (12) and the form is set back to the tag's 9: set again.
        stored = render_channels.overlay({'samples': 9}, dict(render_channels.defaults(), samples=12))
        scene_settings.put(stored, entry('samples'), 9)
        self.assertEqual(render_channels.changed_channels(dict(render_channels.defaults(), samples=12), stored), {'samples': 9})


class Form(unittest.TestCase):
    def test_the_form_names_every_channel(self):
        text = (ROOT / 'kit/MoonRayForModo/render_settings.cfg').read_text(encoding='utf-8')
        self.assertIn('key="%s@en_US"' % render_channels.PACKAGE, text)
        for name, label in render_channels.user_names().items():
            self.assertIn('key="%s"' % name, text)


if __name__ == '__main__':
    unittest.main()
