"""A MoonRay material's main colour and Modo's diffuse: which colour, and what goes where. No Modo."""
import json
import sys
import types
import unittest
from unittest import mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
sys.modules.setdefault('modo', types.ModuleType('modo'))
from moonray_modo import material_diffuse, material_override, node_defaults, properties, shader_library


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

    def two_outputs(self, root, **first):
        return {'version': 1, 'root': root, 'nodes': {
            'first': {'type': 'DwaBaseMaterial', 'parameters': first, 'inputs': {}},
            'second': {'type': 'DwaMetalMaterial', 'parameters': {}, 'inputs': {}},
            'third': {'type': 'DwaBaseMaterial', 'parameters': {}, 'inputs': {}}}}

    def settled(self, root):
        """A linked material on the first output, red, whose output then becomes this one, as the graph editor writes it."""
        item = Item({})
        properties.write(item, material_override.synchronize({}, self.two_outputs('first', albedo=[1, 0, 0])))
        properties.write(item, material_override.synchronize(properties.read(item), self.two_outputs(root, albedo=[1, 0, 0])))
        return item

    def test_a_new_output_with_no_colour_starts_on_its_own(self):
        item = self.settled('second')
        read = properties.read(item)
        self.assertEqual(read['native_shader'], 'DwaMetalMaterial')
        start = node_defaults.start('DwaMetalMaterial', 'metallic_color', shader_library.catalog()['DwaMetalMaterial']['attributes']['metallic_color'])
        self.assertEqual(read['native_parameters']['metallic_color'], start)
        self.assertEqual(read['node_graph']['nodes']['second']['parameters']['metallic_color'], start)
        self.assertEqual(material_diffuse.diffuse(item), start)
        self.assertNotEqual(start, [1, 0, 0])

    def test_also_for_a_new_output_of_the_same_shader(self):
        item = self.settled('third')
        self.assertEqual(properties.read(item)['native_shader'], 'DwaBaseMaterial')
        self.assertNotEqual(material_diffuse.diffuse(item), [1, 0, 0])

    def test_a_new_output_with_a_colour_keeps_it(self):
        graph = self.two_outputs('first', albedo=[1, 0, 0])
        graph['nodes']['second']['parameters']['metallic_color'] = [0, 1, 0]
        item = Item({})
        properties.write(item, material_override.synchronize({}, graph))
        graph = dict(graph, root='second')
        properties.write(item, material_override.synchronize(properties.read(item), graph))
        self.assertEqual(material_diffuse.diffuse(item), [0, 1, 0])
        self.assertEqual(properties.read(item)['native_parameters']['metallic_color'], [0, 1, 0])

    def test_the_same_output_keeps_the_diffuse(self):
        item = self.settled('first')
        self.assertEqual(material_diffuse.diffuse(item), [1, 0, 0])

    def test_a_graph_made_for_the_material_is_not_a_new_output(self):
        item = Item(dict(base(), **{material_diffuse.LINKED: True}), (.1, .2, .3))
        properties.write(item, material_override.synchronize(properties.read(item), self.two_outputs('third')))
        self.assertEqual(material_diffuse.diffuse(item), [.1, .2, .3])

    def test_a_material_of_any_kind_is_marked_with_its_output(self):
        for kind in ('advancedMaterial', properties.LAYER_PREFIX + 'DwaBaseMaterial'):
            item = Item({})
            item.type = kind
            held = item.held = set()
            item.PackageTest = lambda name, held=held: name in held
            item.PackageAdd = held.add
            item.PackageRemove = held.discard
            properties.write(item, material_override.synchronize({}, self.two_outputs('first')))
            self.assertEqual(held, {properties.SHADER_PACKAGE + 'DwaBaseMaterial'})
            properties.write(item, material_override.synchronize(properties.read(item), self.two_outputs('second')))
            self.assertEqual(held, {properties.SHADER_PACKAGE + 'DwaMetalMaterial'})

    def test_every_form_follows_the_marker_not_the_type(self):
        forms = (Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/material_forms.cfg').read_text(encoding='utf-8')
        self.assertNotIn('withTypeIsSelected', forms)
        self.assertIn('item.withPackageIsSelected moonray.shader.DwaMetalMaterial', forms)

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
