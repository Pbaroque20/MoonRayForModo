"""A MoonRay material's main colour and Modo's diffuse: which colour, and what goes where. No Modo."""
import json
import sys
import types
import unittest
from unittest import mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
sys.modules.setdefault('modo', types.ModuleType('modo'))
from moonray_modo import material_diffuse, properties


class Channel:
    def __init__(self, item, name):
        self.item, self.name = item, name

    def get(self):
        return self.item.channels[self.name]

    def set(self, value):
        self.item.channels[self.name] = value
        self.item.sets += 1


class Item:
    type = 'advancedMaterial'
    id = 'material'

    def __init__(self, settings, rgb=(.6, .6, .6)):
        self.settings = settings
        self.sets = 0
        self.channels = {'diffCol.' + axis: value for axis, value in zip('RGB', rgb)}

    def channel(self, name):
        return Channel(self, name)

    def readTag(self, tag):
        return json.dumps(self.settings)

    def setTag(self, tag, value):
        self.settings = json.loads(value)

    def PackageTest(self, name):
        return False

    def PackageAdd(self, name):
        pass


def base(**parameters):
    return {'moonshine_override': True, 'native_shader': 'DwaBaseMaterial', 'native_parameters': parameters}


def graph(albedo):
    return {'version': 1, 'root': 'surface', 'nodes': {'surface': {'type': 'DwaBaseMaterial', 'parameters': {'albedo': albedo}, 'inputs': {}}}}


class ColourKeyTests(unittest.TestCase):
    def test_which_colour(self):
        self.assertEqual(material_diffuse.colour_key('DwaBaseMaterial'), 'albedo')
        self.assertEqual(material_diffuse.colour_key('DwaMetalMaterial'), 'metallic_color')
        self.assertIsNone(material_diffuse.colour_key('DwaLayerMaterial'))
        self.assertIsNone(material_diffuse.colour_key(''))


class ToDiffuseTests(unittest.TestCase):
    def test_colour_goes_to_diffuse(self):
        item = Item({})
        material_diffuse.to_diffuse(item, base(albedo=[.1, .2, .3]))
        self.assertEqual(material_diffuse.diffuse(item), [.1, .2, .3])

    def test_the_same_colour_sets_nothing(self):
        item = Item({}, (.1, .2, .3))
        material_diffuse.to_diffuse(item, base(albedo=[.1, .2, .3]))
        self.assertEqual(item.sets, 0)

    def test_no_colour_set_or_a_plain_modo_material_leaves_it(self):
        for settings in (base(), {}, {'native_shader': 'DwaLayerMaterial', 'native_parameters': {}}):
            item = Item({})
            material_diffuse.to_diffuse(item, settings)
            self.assertEqual(item.sets, 0)

    def test_not_a_material(self):
        item = Item({})
        item.type = 'mesh'
        material_diffuse.to_diffuse(item, base(albedo=[.1, .2, .3]))
        self.assertEqual(item.sets, 0)

    def test_the_graphs_output_node_is_read(self):
        item = Item({})
        material_diffuse.to_diffuse(item, dict(base(), node_graph=graph([.4, .5, .6])))
        self.assertEqual(material_diffuse.diffuse(item), [.4, .5, .6])


class LinkedTests(unittest.TestCase):
    def setUp(self):
        told = mock.patch.dict(sys.modules, {'moonray_modo.property_notifications': types.SimpleNamespace(notify=lambda: None)})
        told.start()
        self.addCleanup(told.stop)

    def test_a_colour_written_links_the_material(self):
        item = Item({})
        properties.write(item, base(albedo=[.1, .2, .3]))
        self.assertTrue(item.settings[material_diffuse.LINKED])
        self.assertEqual(material_diffuse.diffuse(item), [.1, .2, .3])

    def test_a_write_with_no_colour_does_not(self):
        item = Item({})
        properties.write(item, base(roughness=.5))
        self.assertNotIn(material_diffuse.LINKED, item.settings)

    def test_a_linked_material_reads_its_colour_from_the_diffuse(self):
        item = Item(dict(base(albedo=[1, 1, 1]), **{material_diffuse.LINKED: True}), (.1, .2, .3))
        self.assertEqual(properties.read(item)['native_parameters']['albedo'], [.1, .2, .3])
        # So undoing the channel is all it takes: nothing was written.
        item.channels['diffCol.R'] = .9
        self.assertEqual(properties.read(item)['native_parameters']['albedo'], [.9, .2, .3])
        self.assertFalse(material_diffuse.differs(item))
        self.assertEqual(item.settings['native_parameters']['albedo'], [1, 1, 1])

    def test_also_in_the_graphs_output_node(self):
        item = Item(dict(base(), node_graph=graph([1, 1, 1]), **{material_diffuse.LINKED: True}), (.1, .2, .3))
        self.assertEqual(properties.read(item)['node_graph']['nodes']['surface']['parameters']['albedo'], [.1, .2, .3])

    def test_a_material_of_an_older_scene_keeps_its_colour(self):
        item = Item(base(albedo=[1, 1, 1]), (.1, .2, .3))
        self.assertEqual(properties.read(item)['native_parameters']['albedo'], [1, 1, 1])
        self.assertTrue(material_diffuse.differs(item))

    def test_a_colour_being_tried_out_is_shown_over_it(self):
        item = Item(dict(base(albedo=[1, 1, 1]), **{material_diffuse.LINKED: True}), (.1, .2, .3))
        properties.LIVE[item.id] = {'albedo': [.9, .9, .9]}
        try:
            self.assertEqual(properties.read(item)['native_parameters']['albedo'], [.9, .9, .9])
        finally:
            properties.LIVE.pop(item.id)


class FromDiffuseTests(unittest.TestCase):
    def setUp(self):
        # Told only to Modo's forms, which are not here.
        told = mock.patch.dict(sys.modules, {'moonray_modo.property_notifications': types.SimpleNamespace(notify=lambda: None)})
        told.start()
        self.addCleanup(told.stop)

    def test_diffuse_comes_back_to_the_colour(self):
        item = Item(base(albedo=[1, 1, 1], roughness=.5), (.1, .2, .3))
        self.assertTrue(material_diffuse.from_diffuse(item))
        self.assertEqual(item.settings['native_parameters'], {'albedo': [.1, .2, .3], 'roughness': .5})
        self.assertTrue(item.settings[material_diffuse.LINKED])

    def test_also_into_the_graph(self):
        item = Item(dict(base(albedo=[1, 1, 1]), node_graph=graph([1, 1, 1])), (.1, .2, .3))
        self.assertTrue(material_diffuse.from_diffuse(item))
        self.assertEqual(item.settings['node_graph']['nodes']['surface']['parameters']['albedo'], [.1, .2, .3])

    def test_already_the_same_is_no_step(self):
        item = Item(base(albedo=[.1, .2, .3]), (.1, .2, .3))
        before = dict(item.settings)
        self.assertFalse(material_diffuse.from_diffuse(item))
        self.assertEqual(item.settings, before)

    def test_a_plain_modo_material_stays_plain(self):
        item = Item({}, (.1, .2, .3))
        self.assertFalse(material_diffuse.from_diffuse(item))
        self.assertEqual(item.settings, {})

    def test_settings_being_tried_out_are_not_kept(self):
        item = Item(base(albedo=[1, 1, 1]), (.1, .2, .3))
        properties.LIVE[item.id] = {'albedo': [.9, .9, .9]}
        try:
            self.assertFalse(material_diffuse.from_diffuse(item))
        finally:
            properties.LIVE.pop(item.id)


if __name__ == '__main__':
    unittest.main()
