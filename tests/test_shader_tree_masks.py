"""Masks, vertex maps, Texture Locator falloffs and drivers as graph nodes (shader_tree_masks): the nodes as MoonRay
maps, the numbers the meshes carry for the masks, the conversion's hooks and MoonLightIPR's rows. No Modo or renderer
launch."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import nodes, shader_tree_masks as masks, shader_tree_transfer as transfer, textures  # noqa: E402
from moonray_modo import moonlightipr_materials as ipr  # noqa: E402


def emitted(graph):
    lines = []
    with mock.patch.object(textures, '_prepare', lambda source, *rest, **named: str(source)), \
            mock.patch.object(textures, 'missing', lambda source: False):
        nodes.emit({'node_graph': graph, 'color': [.5] * 3}, '/test', [0], lines, {})
    return '\n'.join(lines)


def graph_with(extra, albedo):
    graph = nodes.new('DwaBaseMaterial', {'albedo': [.5, .5, .5]})
    graph['nodes'].update(extra)
    graph['nodes']['surface']['inputs']['albedo'] = albedo
    return graph


def mesh(identity='item1|0|', faces=None, **extra):
    faces = faces or [[0, 1, 2], [0, 2, 3]]
    held = {'name': identity.split('|')[0], 'identity': identity, 'vertices': [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], 'faces': faces,
            'material': 'Mat', 'face_materials': ['Mat'] * len(faces)}
    held.update(extra)
    return held


class Nodes(unittest.TestCase):
    def test_the_nodes_are_listed_under_modo_shader_tree_and_described(self):
        from moonray_modo.node_descriptions import DESCRIPTIONS
        for kind in masks.NODES:
            self.assertIn(kind, nodes.MODO_NODES)
            self.assertIn(kind, nodes.kinds())
            self.assertIn(kind, DESCRIPTIONS)
            nodes.specs(kind)
        self.assertTrue(nodes.connectable('modo_driver', 'value'))
        self.assertFalse(nodes.connectable('modo_mask', 'opacity'))
        self.assertEqual(nodes.specs('modo_mask')['mode']['enum']['Selection Set'], 1)

    def test_a_vertex_map_reads_the_maps_attribute(self):
        graph = graph_with({'w': {'type': 'modo_vertex_map', 'parameters': {'vertex_map': 'Wear'}, 'inputs': {}}}, 'w')
        text = emitted(graph)
        self.assertIn('["primitive_attribute_name"] = "Wear"', text)
        self.assertIn('["primitive_attribute_type"] = 0', text)
        colour = graph_with({'c': {'type': 'modo_vertex_map', 'parameters': {'vertex_map': 'Paint', 'type': 1}, 'inputs': {}}}, 'c')
        self.assertIn('["primitive_attribute_type"] = 3', emitted(colour))
        alpha = graph_with({'a': {'type': 'modo_vertex_map', 'parameters': {'vertex_map': 'Paint', 'type': 2}, 'inputs': {}}}, 'a')
        self.assertIn('"Paint_alpha"', emitted(alpha))

    def test_a_mask_reads_its_own_number_inverted_and_at_its_opacity(self):
        parameters = {'mode': 2, 'tag': 'Top', 'invert': True, 'opacity': .5}
        graph = graph_with({'m': {'type': 'modo_mask', 'parameters': parameters, 'inputs': {}},
                            'b': {'type': 'modo_blend', 'parameters': {}, 'inputs': {'mask': 'm'}}}, 'b')
        text = emitted(graph)
        name = masks.attribute(masks.mask_spec(parameters))
        self.assertTrue(name.startswith(masks.PREFIX))
        self.assertIn('"%s"' % name, text)
        self.assertIn('/invert', text)
        self.assertIn('/opacity', text)
        self.assertEqual(masks.wanted({'Mat': {'node_graph': graph}}), {name: masks.mask_spec(parameters)})
        # A weight-map mask reads the map, which the scene then sends (vertex_maps.named_in finds its name).
        weight = graph_with({'m': {'type': 'modo_mask', 'parameters': {'mode': 4, 'vertex_map': 'Dirt'}, 'inputs': {}}}, 'm')
        self.assertIn('"Dirt"', emitted(weight))
        self.assertEqual(masks.wanted({'Mat': {'node_graph': weight}}), {})

    def test_the_same_mask_has_the_same_name_and_another_another(self):
        a = masks.attribute(masks.mask_spec({'mode': 0, 'items': 'b;a'}))
        self.assertEqual(a, masks.attribute(masks.mask_spec({'mode': 0, 'items': 'a; b', 'tag': 'ignored'})))
        self.assertNotEqual(a, masks.attribute(masks.mask_spec({'mode': 0, 'items': 'a;b', 'instances': True})))
        self.assertNotEqual(masks.attribute(masks.mask_spec({'mode': 1, 'tag': 'S'})), masks.attribute(masks.mask_spec({'mode': 2, 'tag': 'S'})))

    def test_a_falloff_fades_from_its_box_as_its_maps_do(self):
        matrix = [2.0, 0, 0, 0, 0, 2.0, 0, 0, 0, 0, 2.0, 0, 1.0, 0, 0, 1.0]
        cubic = {'shape': 0, 'locator_matrix': matrix, 'start': .5, 'width': .5}
        self.assertEqual(masks.falloff_at(cubic, [1.0, 0.0, 0.0]), 1.0)
        self.assertAlmostEqual(masks.falloff_at(cubic, [1.0, 1.5, 0.0]), .5)
        self.assertEqual(masks.falloff_at(cubic, [3.5, 0, 0]), 0.0)
        self.assertAlmostEqual(masks.falloff_at(dict(cubic, shape=1), [2.0, 1.0, 0.0]), 1 - (2 ** .5 * .5 - .5) / .5)
        self.assertEqual(masks.falloff_at(dict(cubic, shape=2), [1.0, 9.0, 0.0]), 1.0)
        self.assertEqual(masks.falloff_at(dict(cubic, invert=True), [1.0, 0.0, 0.0]), 0.0)
        for shape in range(5):
            text = emitted(graph_with({'f': {'type': 'modo_falloff', 'parameters': dict(cubic, shape=shape), 'inputs': {}}}, 'f'))
            self.assertIn('TransformSpaceMap', text)
        with self.assertRaises(ValueError):
            masks.falloff_frame([0.0] * 16)

    def test_a_driver_passes_on_what_is_wired_to_it(self):
        graph = graph_with({'i': {'type': 'image', 'parameters': {'file': 'C:/a.png', 'uv_map': 'Texture'}, 'inputs': {}},
                            'd': {'type': 'modo_driver', 'parameters': {'driver': 1}, 'inputs': {'value': 'i'}}}, 'd')
        text = emitted(graph)
        self.assertIn('"albedo"', text)
        self.assertNotIn('/node/1_d', text)
        steady = graph_with({'d': {'type': 'modo_driver', 'parameters': {'value': [.25, .5, .75]}, 'inputs': {}}}, 'd')
        self.assertIn('Rgb(0.25, 0.5, 0.75)', emitted(steady).replace('0.250', '0.25'))


class MeshNumbers(unittest.TestCase):
    def snapshot(self, parameters, *meshes):
        graph = graph_with({'m': {'type': 'modo_mask', 'parameters': parameters, 'inputs': {}}}, 'm')
        return {'materials': {'Mat': {'node_graph': graph}}, 'meshes': list(meshes)}, masks.attribute(masks.mask_spec(parameters))

    def test_an_item_mask_is_one_number_for_a_mesh_and_one_for_each_copy(self):
        snapshot, name = self.snapshot({'mode': 0, 'items': 'item1'}, mesh('item1|0|'), mesh('item2|0|'),
                                       mesh('item3|0|', instances=[[1] * 16] * 2, instance_ids=['item1', 'inst9']))
        warnings = []
        masks.apply(snapshot, warnings, {name: {'item1'}})
        first, second, copies = snapshot['meshes']
        self.assertEqual(first['point_attributes'][name]['values'], [[1.0]] * 4)
        self.assertEqual(second['point_attributes'][name]['values'], [[0.0]] * 4)
        self.assertEqual([row[-1]['value'] for row in copies['instance_attributes']], [1.0, 0.0])
        self.assertTrue(warnings)

    def test_a_part_or_selection_set_mask_is_a_number_at_each_corner(self):
        tags = masks.face_tags([('Top', 'A;B'), ('', 'B'), ('Top', '')], [2, 0])
        self.assertEqual(tags, {'part': ['Top', 'Top'], 'pick': ['', 'A;B']})
        snapshot, name = self.snapshot({'mode': 1, 'tag': 'A'}, mesh(_mask_tags=tags))
        masks.apply(snapshot, [])
        self.assertEqual(snapshot['meshes'][0]['corner_attributes'][name]['values'], [[0.0]] * 3 + [[1.0]] * 3)
        snapshot, name = self.snapshot({'mode': 2, 'tag': 'Top'}, mesh(_mask_tags=tags))
        masks.apply(snapshot, [])
        self.assertEqual(snapshot['meshes'][0]['point_attributes'][name]['values'], [[1.0]] * 4)
        # Read through Modo's evaluated geometry: a surface's own Part; no Selection Sets.
        snapshot, name = self.snapshot({'mode': 2, 'tag': 'Top'}, mesh(evaluated_geometry=True, _part='Top'))
        masks.apply(snapshot, [])
        self.assertEqual(snapshot['meshes'][0]['point_attributes'][name]['values'][0], [1.0])
        warnings = []
        snapshot, name = self.snapshot({'mode': 1, 'tag': 'A'}, mesh(evaluated_geometry=True))
        masks.apply(snapshot, warnings)
        self.assertEqual(snapshot['meshes'][0]['point_attributes'][name]['values'][0], [0.0])
        self.assertTrue(warnings)

    def test_a_material_tag_mask_goes_by_each_faces_tag(self):
        snapshot, name = self.snapshot({'mode': 3, 'tag': 'Rust'}, mesh(face_materials=['Rust', 'Mat']))
        masks.apply(snapshot, [])
        self.assertEqual(snapshot['meshes'][0]['corner_attributes'][name]['values'], [[1.0]] * 3 + [[0.0]] * 3)

    def test_polygon_tags_are_wanted_only_for_part_and_selection_set_masks(self):
        snapshot, _ = self.snapshot({'mode': 0, 'items': 'a'})
        self.assertFalse(masks.tags_wanted(snapshot['materials']))
        snapshot, _ = self.snapshot({'mode': 2, 'tag': 'x'})
        self.assertTrue(masks.tags_wanted(snapshot['materials']))
        self.assertTrue(masks.tags_newly_wanted(snapshot['materials'], [mesh()]))
        self.assertFalse(masks.tags_newly_wanted(snapshot['materials'], [mesh(_mask_tags={})]))


class Conversion(unittest.TestCase):
    def test_a_nested_mask_is_a_mask_node_once_for_all_its_layers(self):
        builder = transfer.Builder()
        info = {'identity': 'mask009', 'name': 'Top', 'tag_type': 'part', 'tag': 'Top', 'items': [], 'instances': False}
        value = masks.mask_value(builder, info)
        self.assertEqual(masks.mask_value(builder, info), value)
        node = builder.nodes[value[1]]
        self.assertEqual((node['type'], node['parameters']['mode'], node['parameters']['tag']), ('modo_mask', 2, 'Top'))
        both = masks.mask_value(builder, dict(info, identity='mask010', items=['mesh1']))
        self.assertEqual(builder.nodes[both[1]]['type'], 'multiply')
        self.assertEqual(masks.mask_value(builder, {'identity': 'm', 'tag_type': '', 'tag': '', 'items': []}), ('c', [1.0, 1.0, 1.0]))
        # Laid in by a Modo Blend's mask, it validates and is wanted.
        graph = nodes.new('DwaBaseMaterial', {})
        graph['nodes'].update(builder.nodes)
        graph['nodes']['blend'] = {'type': 'modo_blend', 'parameters': {}, 'inputs': {'mask': value[1]}}
        graph['nodes']['surface']['inputs']['albedo'] = 'blend'
        nodes.validate(graph)
        self.assertEqual(len(masks.wanted({'m': {'node_graph': graph}})), 2)

    def test_a_gradient_on_a_driver_reads_the_driver_node(self):
        builder = transfer.Builder()
        chain = builder.add('drv', 'image', 'image', {'file': 'C:/d.png', 'uv_map': 'Texture'})
        layer = {'identity': 'grad1', 'name': 'Gradient', 'kind': 'gradient', 'effect': 'diffCol', 'invert': False,
                 'gradient': {'input': 'driverB', 'positions': [0.0, 1.0], 'colors': [[1, 0, 0], [0, 0, 1]], 'alpha': [1.0, 0.5]}}
        self.assertEqual(masks.layer_key(layer), 'gradient:driverB')
        masks.CHECKS['gradient:driverB'](layer, 'diffCol')
        colour, mask = masks.FOREGROUNDS['gradient:driverB'](builder, layer, 'diffCol', None, drivers={'driverB': chain})
        node = builder.nodes[colour[1]]
        driver = builder.nodes[node['inputs']['input']]
        self.assertEqual((driver['type'], driver['parameters']['driver'], driver['inputs']['value']), ('modo_driver', 1, chain[1]))
        self.assertEqual(builder.nodes[mask[1]]['parameters']['output'], 1)
        graph = nodes.new('DwaBaseMaterial', {})
        graph['nodes'].update(builder.nodes)
        graph['nodes']['surface']['inputs']['albedo'] = colour[1]
        text = emitted(graph)
        self.assertIn('RampMap', text)
        self.assertIn('d.png', text)
        # No layer set the driver: it is 0.
        unset = transfer.Builder()
        colour, _ = masks.FOREGROUNDS['gradient:driverB'](unset, dict(layer, gradient=dict(layer['gradient'], input='driverB')), 'diffCol', None)
        driver = unset.nodes[unset.nodes[colour[1]]['inputs']['input']]
        self.assertEqual(driver['parameters'].get('value'), [0.0, 0.0, 0.0])

    def test_a_weight_map_texture_reads_a_vertex_map_node(self):
        builder = transfer.Builder()
        layer = {'identity': 'wm1', 'kind': 'gradient', 'effect': 'diffCol',
                 'gradient': {'input': '@vmap', 'vmap': 'Wear', 'positions': [0.0, 1.0], 'colors': [[0, 0, 0], [1, 1, 1]]}}
        colour, mask = masks.FOREGROUNDS['gradient:@vmap'](builder, layer, 'diffCol', None)
        self.assertIsNone(mask)
        reading = builder.nodes[builder.nodes[colour[1]]['inputs']['input']]
        self.assertEqual((reading['type'], reading['parameters']['vertex_map']), ('modo_vertex_map', 'Wear'))
        graph = nodes.new('DwaBaseMaterial', {})
        graph['nodes'].update(builder.nodes)
        graph['nodes']['surface']['inputs']['albedo'] = colour[1]
        text = emitted(graph)
        self.assertIn('"Wear"', text)
        self.assertIn('RampMap', text)
        with self.assertRaises(transfer.Refused):
            masks.CHECKS['gradient:@vmap'](dict(layer, gradient={'input': '@vmap', 'vmap': ''}), 'diffCol')


class MoonLightIPR(unittest.TestCase):
    def test_mask_vertex_map_and_falloff_are_rows(self):
        mask = {'type': 'modo_mask', 'parameters': {'mode': 2, 'tag': 'Top', 'invert': True, 'opacity': .5}, 'inputs': {}}
        found = masks.ipr_leaf({'nodes': {}}, mask, None)
        self.assertEqual(found[0]['gradient']['vmap'], masks.attribute(masks.mask_spec(mask['parameters'])))
        self.assertEqual(found[0]['gradient']['colors'], [[.5] * 3, [0.0] * 3])
        linear = masks.falloff_row({'shape': 2, 'locator_matrix': masks.IDENTITY, 'start': .5, 'width': .5})
        self.assertEqual(linear['gradient']['sample'], 'textureLocal')
        self.assertIsNone(masks.falloff_row({'shape': 0}))
        self.assertIsNone(masks.falloff_row({'shape': 1, 'locator_matrix': [1.0, 0, 0, 0, 0, 2.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]}))

    def test_a_blend_masked_by_a_mask_is_a_layer_mask_over_its_layer(self):
        graph = graph_with({'i': {'type': 'image', 'parameters': {'file': 'C:/a.png', 'uv_map': 'Texture'}, 'inputs': {}},
                            'j': {'type': 'image', 'parameters': {'file': 'C:/b.png', 'uv_map': 'Texture'}, 'inputs': {}},
                            'm': {'type': 'modo_mask', 'parameters': {'mode': 2, 'tag': 'Top'}, 'inputs': {}},
                            'b': {'type': 'modo_blend', 'parameters': {'blend': 1, 'opacity': .75}, 'inputs': {'bg': 'i', 'fg': 'j', 'mask': 'm'}}}, 'b')
        rows = ipr.graph_expression(graph, 'b', 'diffCol')
        self.assertEqual([row['kind'] for row in rows], ['imageMap', 'gradient', 'imageMap'])
        self.assertEqual(rows[1]['effect'], 'layerMask')
        self.assertEqual(rows[1]['mask_target'], rows[2]['identity'])
        self.assertEqual((rows[2]['blend'], rows[2]['opacity']), ('multiply', .75))

    def test_a_gradient_on_a_driver_puts_the_drivers_rows_first(self):
        data = {'input': 'driverA', 'positions': [0.0, 1.0], 'colors': [[1, 0, 0], [0, 0, 1]]}
        graph = graph_with({'i': {'type': 'image', 'parameters': {'file': 'C:/a.png', 'uv_map': 'Texture'}, 'inputs': {}},
                            'd': {'type': 'modo_driver', 'parameters': {'driver': 0}, 'inputs': {'value': 'i'}},
                            'g': {'type': 'modo_procedural', 'parameters': {'gradient': json.dumps(data)}, 'inputs': {'input': 'd'}},
                            'c': {'type': 'constant', 'parameters': {'value': [.2, .2, .2]}, 'inputs': {}},
                            'b': {'type': 'modo_blend', 'parameters': {}, 'inputs': {'bg': 'c', 'fg': 'g'}}}, 'b')
        rows = ipr.graph_expression(graph, 'b', 'diffCol')
        self.assertEqual(rows[0]['effect'], 'driverA')
        self.assertEqual(rows[-1]['gradient']['input'], 'driverA')
        self.assertEqual(rows[-1]['effect'], 'diffCol')

    def test_an_rgb_vertex_map_is_three_rows_of_its_channels(self):
        graph = graph_with({'c': {'type': 'modo_vertex_map', 'parameters': {'vertex_map': 'Paint', 'type': 1}, 'inputs': {}}}, 'c')
        rows = ipr.graph_expression(graph, 'c', 'diffCol')
        self.assertEqual([row['gradient']['vmap'] for row in rows], ['Paint@rgb0', 'Paint@rgb1', 'Paint@rgb2'])
        self.assertEqual([row['blend'] for row in rows], ['normal', 'add', 'add'])
        try:
            from moonray_modo.moonlightipr_scene import with_weights
        except ImportError:
            return
        available = {}
        held = mesh(point_attributes={'Paint': {'kind': 'color', 'values': [[.1, .2, .3]] * 4}})
        with_weights(held, available, ['@vmap:Paint@rgb1'])
        self.assertEqual(available['@vmap:Paint@rgb1'][0], (.2, 0.0))


if __name__ == '__main__':
    unittest.main()
