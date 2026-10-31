"""MoonRay's display filters as Modo items: in the catalog, written into the scene with what they take in, each a
buffer of the preview and a channel of the final EXR. No Modo or renderer launch."""
import sys
import unittest
from unittest import mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import entities, outputs, rdla

GREY = {'identity': 'filter1', 'name': 'Grey', 'class': 'ColorCorrectDisplayFilter',
        'parameters': {'input': 'Beauty', 'saturation': 0.0}}
EDGES = {'identity': 'filter2', 'name': 'Edges', 'class': 'ToonDisplayFilter',
         'parameters': {'input_diffuse': 'Grey', 'input_depth': 'Camera depth'}}


def scene(*filters, **extra):
    result = {'camera': {'matrix': rdla.IDENTITY, 'focal_mm': 50, 'film_mm': 36}, 'meshes': [], 'entities': list(filters)}
    result.update(extra)
    return result


class DisplayFilterTests(unittest.TestCase):
    def test_toon_lines_without_gaps_is_a_source_override(self):
        toon = {'identity': 'toon', 'name': 'Toon', 'class': 'ToonDisplayFilter', 'parameters': {'output_mode': 1}}
        with mock.patch.object(entities, 'toon_close_gaps', lambda: True):
            self.assertIs(entities.completed_filters([toon], [])[0]['parameters'].get('close_line_gaps'), True)
        with mock.patch.object(entities, 'toon_close_gaps', lambda: False):
            self.assertNotIn('close_line_gaps', entities.completed_filters([toon], [])[0]['parameters'])
        self.assertEqual(entities.completed_filters([toon], [])[0]['parameters']['output_mode'], 1)
        self.assertIn('close_line_gaps', entities.catalog()['ToonDisplayFilter']['attributes'])

    def test_catalog_has_every_display_filter_of_the_source(self):
        named = set(entities.classes('displayfilter'))
        source = Path(__file__).resolve().parents[1] / 'upstream/openmoonray/moonray'
        expected = {p.stem for p in source.glob('moonshine/dso/displayfilter/*/*DisplayFilter.json')}
        expected |= {p.stem for p in source.glob('moonray/dso/displayfilter/*/*DisplayFilter.json')}
        self.assertEqual(named, expected)
        self.assertEqual(len(named), 18)
        attributes = entities.catalog()['ColorCorrectDisplayFilter']['attributes']
        self.assertEqual(attributes['input']['interface'], 'RENDEROUTPUT')
        self.assertEqual(attributes['saturation']['default'], 1.0)
        self.assertEqual(attributes['mix']['group'], 'Advanced')
        self.assertFalse(entities.catalog()['ColorCorrectDisplayFilter']['placed'])

    def test_inputs_are_picked_from_outputs_and_filters(self):
        self.assertEqual(entities.presentation('ColorCorrectDisplayFilter', 'input'), 'pick')
        self.assertEqual(entities.reference_category(entities.catalog()['ToonDisplayFilter']['attributes']['input_albedo']), 'renderoutput')
        names = entities.output_names([{'name': 'my_lpe', 'kind': 'lpe'}, {'name': 'crypto_object', 'kind': 'cryptomatte'}])
        self.assertEqual(names[0], 'Beauty')
        self.assertIn('Camera depth', names)
        self.assertIn('my_lpe', names)
        self.assertNotIn('crypto_object', names)
        self.assertEqual(entities.starting('ColorCorrectDisplayFilter'), {'input': 'Beauty'})

    def test_final_render_writes_filters_and_their_pictures(self):
        text = rdla.scene_text(scene(GREY, EDGES), output_file='final.exr')
        self.assertIn('ColorCorrectDisplayFilter("/modo/entity/filter1") {', text)
        self.assertIn('["input"] = RenderOutput("/modo/displayfilter/input/Beauty"),', text)
        # A filter taking in another filter names it.
        self.assertIn('["input_diffuse"] = ColorCorrectDisplayFilter("/modo/entity/filter1"),', text)
        self.assertIn('["input_depth"] = RenderOutput("/modo/displayfilter/input/Camera depth"),', text)
        # Each filter is a channel of the EXR, named after its item.
        block = text[text.index('RenderOutput("/modo/aov/displayfilter_filter1")'):]
        block = block[:block.index('}')]
        self.assertIn('["file_name"] = "final.exr"', block)
        self.assertIn('["channel_name"] = "Grey"', block)
        self.assertIn('["result"] = 15', block)
        self.assertIn('["display_filter"] = ColorCorrectDisplayFilter("/modo/entity/filter1")', block)
        # What the filters take in is written, but out of the EXR.
        inputs = text[text.index('RenderOutput("/modo/displayfilter/input/Camera depth") {'):]
        inputs = inputs[:inputs.index('}')]
        self.assertNotIn('final.exr', inputs)
        self.assertIn('["result"] = 2', inputs)

    def test_no_filters_no_change(self):
        self.assertNotIn('displayfilter', rdla.scene_text(scene(), output_file='final.exr'))

    def test_preview_shows_a_filter_as_a_buffer(self):
        key = entities.filter_key(GREY)
        self.assertIn(key, outputs.preview(scene(GREY)))
        self.assertEqual(outputs.display_kind(scene(GREY), key), 'beauty')
        text = rdla.scene_text(scene(GREY, preview_buffer_files={key: 'grey.exr'}))
        self.assertIn('ColorCorrectDisplayFilter("/modo/entity/filter1") {', text)
        self.assertIn('RenderOutput("/modo/preview/%s")' % key, text)
        self.assertIn('["display_filter"] = ColorCorrectDisplayFilter("/modo/entity/filter1")', text)
        self.assertIn('RenderOutput("/modo/displayfilter/input/Beauty")', text)
        # Another buffer shown: the filters are left out.
        self.assertNotIn('DisplayFilter(', rdla.scene_text(scene(GREY, preview_buffer_files={'beauty': 'b.exr'})))

    def test_a_runtime_without_the_plugin_leaves_the_filter_out(self):
        older = scene(GREY, _display_filter_classes=['ImageDisplayFilter'])
        text = rdla.scene_text(older, output_file='final.exr')
        self.assertNotIn('ColorCorrectDisplayFilter', text)
        self.assertNotIn(entities.filter_key(GREY), outputs.preview(older))
        self.assertTrue(any('display filter Grey' in w for w in older['warnings']))
        self.assertIn('ColorCorrectDisplayFilter(', rdla.scene_text(scene(GREY, _display_filter_classes=['ColorCorrectDisplayFilter']), output_file='final.exr'))

    def test_an_input_that_is_no_output_is_refused(self):
        wrong = dict(GREY, parameters={'input': 'Nothing'})
        with self.assertRaisesRegex(ValueError, 'no output of the render'):
            rdla.scene_text(scene(wrong), output_file='final.exr')


if __name__ == '__main__':
    unittest.main()
