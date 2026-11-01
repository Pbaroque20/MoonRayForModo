"""What of a scene is left out is said in Notices, and a group's blend mode the plugin lacks stops nothing. No Modo."""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import layers, left_out


def item(kind='mask', name='It', parent=None, **channels):
    return types.SimpleNamespace(type=kind, name=name, id=name, parent=parent, channels=channels)


def channel(held, name, default=None):
    return held.channels.get(name, default)


class GroupBlends(unittest.TestCase):
    def test_a_blend_the_plugin_lacks_is_drawn_as_normal(self):
        for blend in ('normalmult', 'normalblend'):
            top = item(parent=None, blend=blend)
            top.parent = item('polyRender')
            self.assertEqual(layers.texture_groups(item('imageMap', parent=top), channel)[0]['blend'], 'normal')

    def test_the_others_stay_as_they_are(self):
        top = item(parent=item('polyRender'), blend='multiply')
        self.assertEqual(layers.texture_groups(item('imageMap', parent=top), channel)[0]['blend'], 'multiply')

    def test_and_a_notice_says_so(self):
        said = left_out.group_blends([item(name='Skin', blend='normalmult'), item(name='Eye', blend='add')], channel)
        self.assertEqual(said, ['Group Skin: its blend mode normalmult is drawn as Normal.'])


class Materials(unittest.TestCase):
    def test_a_kind_the_plugin_does_not_read_is_named(self):
        self.assertIn('Unreal', left_out.unread_material(item('unrealShader', 'Floor'), channel))
        self.assertIn('Hair', left_out.unread_material(item('material.hairMaterial', 'Fuzz'), channel))

    def test_one_it_reads_or_one_switched_off_is_not(self):
        self.assertIsNone(left_out.unread_material(item('advancedMaterial'), channel))
        self.assertIsNone(left_out.unread_material(item('glTFShader', enable=0), channel))


class VertexMaps(unittest.TestCase):
    def test_a_map_asked_for_deep_in_a_stack_is_named(self):
        materials = {'a': {'material_stack': [{'layers': [{'gradient': {'input': '@vmap', 'vmap': 'Cornea'}}]}]}, 'b': {'color': [1, 1, 1]}}
        self.assertIn('Cornea', left_out.vertex_maps_lost(materials)[0])

    def test_nothing_is_said_where_none_is(self):
        self.assertEqual(left_out.vertex_maps_lost({'a': {'layers': [{'gradient': {'input': 'u'}}]}}), [])


class MoonLightIPR(unittest.TestCase):
    def says(self, words, **scene):
        return any(words in line for line in left_out.moonlightipr(scene))

    def test_sheen(self):
        self.assertTrue(self.says('sheen of velvet', materials={'velvet': {'sheen': .5}}))
        self.assertTrue(self.says('sheen of velvet', materials={'velvet': {'material_stack': [{}, {'sheen': .5}]}}))
        self.assertFalse(self.says('sheen', materials={'plain': {'sheen': 0}}))

    def test_shadow_distances(self):
        self.assertTrue(self.says('shadow distances', production={'lights': {'a': {'max_shadow_distance': 3.0}}}))
        self.assertTrue(self.says('shadow distances', entities=[{'class': 'SpotLight', 'parameters': {'min_shadow_distance': 1}}]))
        self.assertFalse(self.says('shadow distances', production={'lights': {'a': {'max_shadow_distance': 0}}}, entities=[{'class': 'Camera', 'parameters': {'max_shadow_distance': 1}}]))

    def test_fog(self):
        self.assertTrue(self.says('lights fog', materials={'f': {'volume_only': True}}))
        self.assertFalse(self.says('lights fog', materials={'f': {}}))

    def test_a_plain_scene_hears_nothing(self):
        self.assertEqual(left_out.moonlightipr({'materials': {'a': {'color': [1, 1, 1]}}}), [])


class Wiring(unittest.TestCase):
    def read(self, name):
        return (ROOT / 'kit/MoonRayForModo/python/moonray_modo' / name).read_text(encoding='utf-8')

    def test_the_notices_reach_the_scene(self):
        host = self.read('host.py')
        self.assertIn('left_out.group_blends(', host)
        self.assertIn('left_out.unread_material(', host)
        self.assertIn('left_out.vertex_maps_lost(', host)
        self.assertIn('left_out.moonlightipr(scene)', self.read('moonlightipr_scene.py'))

    def test_solid_projections_say_where_they_are_drawn(self):
        source = self.read('layers.py')
        self.assertNotIn('MoonLightIPR laid on', source.replace('\n', ' '))
        self.assertNotIn('drawn in 3D by MoonRay', source)


if __name__ == '__main__':
    unittest.main()
