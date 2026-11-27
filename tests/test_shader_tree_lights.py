"""A light's Shader Tree images for Move Shader Tree Textures to MoonShine Graphs (shader_tree_lights): which layers
move as records, which stay and why, and the records in the scene's light settings. No Modo or renderer launch."""
import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
for _name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(_name, types.ModuleType(_name))
from moonray_modo import shader_tree_lights as lights  # noqa: E402

SPOT = {'id': 'spot', 'name': 'Spot Light', 'type': 'spotLight', 'on': True, 'ies': ''}


def layer(identity, kind='imageMap', on=True, source=True, **extra):
    held = {'id': identity, 'name': identity + ' (Image)', 'type': kind, 'on': on, 'effect': 'lightColor', 'opacity': 1.0, 'blend': 'normal',
            'source': {'filename': 'C:/images/%s.png' % identity, 'colorspace': '(default)', 'clip': identity} if source and kind == 'imageMap' else None}
    held.update(extra)
    return held


class Plan(unittest.TestCase):
    def test_an_image_on_a_light_moves(self):
        moving, left, kept = lights.plan(SPOT, [layer('a')])
        self.assertEqual([m['id'] for m in moving], ['a'])
        self.assertEqual(left, [])

    def test_a_layer_that_is_not_an_image_stays_and_says_why(self):
        moving, left, _ = lights.plan(SPOT, [layer('c', kind='constant'), layer('g', kind='gradient')])
        self.assertEqual(moving, [])
        self.assertEqual([name for name, _ in left], ['c (Image)', 'g (Image)'])
        self.assertIn('not an image', left[0][1])

    def test_a_layer_off_or_with_no_image_does_not_move(self):
        moving, left, _ = lights.plan(SPOT, [layer('off', on=False), layer('none', source=False)])
        self.assertEqual(moving, [])
        self.assertEqual(left, [('none (Image)', 'it has no image')])

    def test_a_light_switched_off_keeps_its_images(self):
        moving, left, _ = lights.plan(dict(SPOT, on=False), [layer('a')])
        self.assertEqual(moving, [])
        self.assertIn('switched off', left[0][1])

    def test_an_ies_profile_stays_and_says_why(self):
        photometric = {'id': 'p', 'name': 'Photometric', 'type': 'photometryLight', 'on': True, 'ies': 'C:/ies/a.ies'}
        moving, left, _ = lights.plan(photometric, [])
        self.assertEqual(moving, [])
        self.assertIn('IES', left[0][1])

    def test_records_of_layers_that_are_gone_are_dropped_and_moved_layers_kept(self):
        records = [lights.record(layer('a'), SPOT), lights.record(layer('gone'), SPOT)]
        moving, left, kept = lights.plan(SPOT, [layer('a', on=False)], records)
        self.assertEqual(moving, [])
        self.assertEqual([r['layer'] for r in kept], ['a'])

    def test_a_moved_layer_switched_on_again_moves_again(self):
        records = [lights.record(layer('a'), SPOT)]
        moving, _, kept = lights.plan(SPOT, [layer('a')], records)
        self.assertEqual([m['id'] for m in moving], ['a'])


class Records(unittest.TestCase):
    def test_a_record_names_the_image_alone(self):
        held = lights.record(layer('a', opacity=.5), SPOT)
        self.assertEqual(held['source']['filename'], 'C:/images/a.png')
        self.assertEqual((held['layer'], held['light'], held['effect'], held['opacity']), ('a', 'spot', 'lightColor', .5))

    def test_records_go_into_the_lights_entry_and_out_again(self):
        settings = {'production': {'lights': {'spot': {'cookie_file': 'C:/c.png'}}, 'objects': {}}, 'other': 1}
        records = [lights.record(layer('a'), SPOT)]
        made = lights.merged_settings(settings, 'spot', records)
        self.assertEqual(made['production']['lights']['spot']['cookie_file'], 'C:/c.png')
        self.assertEqual(made['production']['lights']['spot'][lights.RECORD_KEY], records)
        self.assertNotIn(lights.RECORD_KEY, settings['production']['lights']['spot'])
        back = lights.merged_settings(made, 'spot', [])
        self.assertEqual(back, settings)
        alone = lights.merged_settings({}, 'area', records)
        self.assertEqual(lights.merged_settings(alone, 'area', [])['production']['lights'], {})

    def test_the_kit_renders_a_light_with_a_record_as_without(self):
        from moonray_modo import lighting
        scene = {'lights': [{'kind': 'SpotLight', 'identity': 'spot', 'name': 'Spot', 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
                             'color': [1, 1, 1], 'intensity': 1.0, 'cone': 45, 'soft_edge': 0, 'radius': .01}],
                 'production': {'lights': {}}}
        plain, recorded = [], []
        try:
            lighting.emit(scene, [], 0, plain)
            with_record = dict(scene, production=lights.merged_settings(scene, 'spot', [lights.record(layer('a'), SPOT)])['production'])
            lighting.emit(with_record, [], 0, recorded)
        except (ImportError, AttributeError) as exc:
            self.skipTest('lighting needs Modo here: %s' % exc)
        self.assertEqual(plain, recorded)

    def test_the_report_says_what_moved_and_what_stayed(self):
        report = lights.Report()
        report.moved.append(('a (Image)', 'Spot Light'))
        report.left.append(('Photometric', lights.IES_NOTE))
        report.unloaded.append('a')
        text = '\n'.join(report.lines())
        self.assertIn('1 image layer moved, 1 image clip unloaded', text)
        self.assertIn('Left on the light: Photometric', text)


if __name__ == '__main__':
    unittest.main()
