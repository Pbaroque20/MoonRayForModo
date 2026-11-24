"""Cryptomatte in Render Settings' XPU and XPU2 Outputs (AOVs): a tick a category (Cryptomatte: Objects, Cryptomatte:
Materials), kept among the scene's outputs (custom_aovs, as the Light Path Expressions window and the preview window's
buffer list keep it), so that MoonRay XPU and XPU2 (and Vector) write it beside the beauty: in the EXR of a render to
files with its manifest, and as a buffer of a preview's Render. tools/compare_cryptomatte_xpu.py renders it with each
engine and compares the IDs and coverage with MoonRay Vector's."""
import pathlib
import re
import sys
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))

from moonray_modo import cryptomatte, outputs, rdla, scene_settings  # noqa: E402


def tick(category):
    return next(entry for entry in scene_settings.FIELDS if entry['key'] == 'aov_crypto_' + category)


def scene(custom_aovs, **more):
    held = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 5, 1], 'focal_mm': 50.0, 'film_mm': 36.0},
            'materials': {'red': {'name': 'Red', 'color': [.8, .1, .1]}, 'blue': {'name': 'Blue', 'color': [.1, .1, .8]}},
            'meshes': [{'name': 'Box', 'identity': 'box', 'material': 'red', 'faces': [[0, 3, 2, 1]],
                        'vertices': [[-1, 0, -1], [1, 0, -1], [1, 0, 1], [-1, 0, 1]]},
                       {'name': 'Card', 'identity': 'card', 'material': 'blue', 'faces': [[0, 1, 2]],
                        'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]]}],
            'lights': [], 'environments': [], 'custom_aovs': custom_aovs, '_crypto_categories': True}
    held.update(more)
    return held


def crypto_outputs(text, prefix='/modo/aov/'):
    """{output name: its attributes' text} of the Cryptomatte outputs (result 13)."""
    return {name: body for name, body in re.findall(r'RenderOutput\("%s([^"]+)"\) \{(.*?)\n\}' % re.escape(prefix), text, re.S)
            if '["result"] = 13' in body}


class Ticks(unittest.TestCase):
    def test_both_categories_are_in_the_xpu_and_xpu2_section(self):
        entries = next(entries for label, _, entries in scene_settings.GROUPS if label == 'XPU and XPU2 Outputs (AOVs)')
        crypto = [e for e in entries if e['path'] == scene_settings.CRYPTOMATTE_PATH]
        self.assertEqual([(e['key'], e['label'], e['kind']) for e in crypto],
                         [('aov_crypto_object', 'Cryptomatte: Objects', 'member'), ('aov_crypto_material', 'Cryptomatte: Materials', 'member')])
        self.assertTrue(all(e['tip'].isascii() for e in crypto))

    def test_the_form_has_their_commands(self):
        form = (ROOT / 'kit/MoonRayForModo/render_settings.cfg').read_text(encoding='utf-8')
        self.assertIn('moonray.render.aov_crypto_object ?', form)
        self.assertIn('moonray.render.aov_crypto_material ?', form)

    def test_a_new_scene_has_objects_ticked_and_materials_not(self):
        values = scene_settings.complete({})
        self.assertTrue(scene_settings.get(values, tick('object')))
        self.assertFalse(scene_settings.get(values, tick('material')))

    def test_ticking_materials_adds_its_output_in_a_part_of_its_own(self):
        stored = {}
        scene_settings.put(stored, tick('material'), 1)
        entries = stored['custom_aovs']
        self.assertEqual([(v['name'], v['category'], v['part']) for v in entries],
                         [('crypto_object', 'object', 'crypto_object'), ('crypto_material', 'material', 'crypto_material')])
        self.assertTrue(scene_settings.get(scene_settings.complete(stored), tick('material')))
        # Ticked again: nothing more.
        scene_settings.put(stored, tick('material'), 1)
        self.assertEqual(len(stored['custom_aovs']), 2)

    def test_taking_one_away_leaves_the_other_in_the_first_part(self):
        stored = {}
        scene_settings.put(stored, tick('material'), 1)
        scene_settings.put(stored, tick('object'), 0)
        self.assertEqual([(v['name'], v['category'], v['part']) for v in stored['custom_aovs']], [('crypto_material', 'material', '')])
        self.assertFalse(scene_settings.get(scene_settings.complete(stored), tick('object')))
        scene_settings.put(stored, tick('material'), 0)
        self.assertEqual(stored['custom_aovs'], [])

    def test_other_outputs_are_kept_and_a_name_taken_is_not_reused(self):
        lpe = {'name': 'crypto_material', 'kind': 'lpe', 'expression': 'CD.*L'}
        entries = outputs.with_cryptomatte([lpe], 'material', True)
        self.assertEqual([(v['name'], v['kind']) for v in entries], [('crypto_material', 'lpe'), ('crypto_material_1', 'cryptomatte')])
        self.assertEqual([v['name'] for v in outputs.with_cryptomatte(entries, 'material', False)], ['crypto_material'])

    def test_a_cryptomatte_added_in_the_outputs_window_shows_ticked(self):
        held = [{'name': 'mattes', 'kind': 'cryptomatte', 'category': 'material'}]
        self.assertTrue(scene_settings.get(scene_settings.complete({'custom_aovs': held}), tick('material')))
        self.assertFalse(scene_settings.get(scene_settings.complete({'custom_aovs': held}), tick('object')))


class Written(unittest.TestCase):
    """What the ticks make MoonRay XPU and XPU2 write: the scene text is the same for both (XPU2 reads MoonRay's)."""

    def both(self):
        stored = {}
        scene_settings.put(stored, tick('material'), 1)
        return stored['custom_aovs']

    def test_a_render_to_files_writes_each_category_with_its_manifest(self):
        for xpu2 in (False, True):
            text = rdla.scene_text(scene(self.both(), _xpu2=xpu2), 64, 36, 1, 0.0, r'C:\renders\shot.0001.exr')
            found = crypto_outputs(text)
            self.assertEqual(sorted(found), ['crypto_material', 'crypto_object'])
            self.assertIn('["cryptomatte_id_channel"] = 0', found['crypto_object'])
            self.assertIn('["cryptomatte_id_channel"] = 1', found['crypto_material'])
            self.assertIn('["file_part"] = "crypto_material"', found['crypto_material'])
            for category in ('object', 'material'):
                block = re.search(r'Metadata\("/modo/outputMetadata/%s"\) (.*)' % category, text).group(1)
                self.assertIn('cryptomatte/d44fae7/manifest', block)
            # MurmurHash3 of the names, as MoonRay's own manifest has them.
            self.assertIn('%08x' % cryptomatte.value('Red [red]', 'material', None, None), text)
            self.assertIn('%08x' % cryptomatte.value('Box [box]', 'object', None, None), text)

    def test_a_preview_renders_each_as_a_buffer(self):
        with mock.patch('moonray_modo.native.pbr_validity', return_value=False):
            files = {key: 'C:/p/%s.exr' % key for key in outputs.preview(scene(self.both()))}
            self.assertIn('crypto_object', files)
            self.assertIn('crypto_material', files)
            text = rdla.scene_text(scene(self.both(), preview_buffer_files=files, _xpu2=True), 64, 36, 1, 0.0, None)
        self.assertEqual(sorted(crypto_outputs(text, '/modo/preview/')), ['crypto_material', 'crypto_object'])

    def test_unticked_none_is_written(self):
        text = rdla.scene_text(scene([], _xpu2=True), 64, 36, 1, 0.0, r'C:\renders\shot.0001.exr')
        self.assertEqual(crypto_outputs(text), {})
        self.assertNotIn('modo_object_id', text)


class Export(unittest.TestCase):
    def test_export_no_longer_adds_a_category_behind_a_tick_taken_off(self):
        source = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/panel_tools.py').read_text(encoding='utf-8')
        self.assertNotIn('_render_missing_cryptomattes', source)


if __name__ == '__main__':
    unittest.main()
