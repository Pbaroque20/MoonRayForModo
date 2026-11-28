"""Move Shader Tree Textures to MoonShine Graphs (shader_tree_transfer): what a Shader Tree layer becomes in a graph,
how a graph is brought up to date in place, the constant values read back from a Modo material's MoonRay text, and
Open Scene as MoonShine's reading and copying of a scene file (moonshine_open). No Modo or renderer launch."""
import json
import math
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import coordinates, nodes, shader_tree_transfer as transfer, textures  # noqa: E402

BASES = {'diffCol': [.5, .5, .5], 'rough': .4, 'metallic': 0, 'normal': [.5, .5, 1], 'groupMask': 1, 'dissolve': 0, 'lumiCol': [0, 0, 0]}
POST = {'roughness_ramp': [(0.0, 0.0), (0.5, 0.5), (1.0, 0.9)], 'specular_ramp': [(0.0, 1.0), (1.0, 2.0)], 'specular_colour': [.04, .04, .04],
        'diffuse_amount': 1.0, 'emission_amount': 1.0, 'bump_strength': .005}


def image(identity, effect='diffCol', **extra):
    layer = {'identity': identity, 'name': identity + ' (Image)', 'kind': 'imageMap', 'effect': effect, 'opacity': 1.0, 'blend': 'normal',
             'invert': False, 'groups': [], 'projection': 'uv', 'uv_map': 'Texture', 'uv_matrix': [1, 0, 0, 0, 1, 0], 'rotation': 0.0,
             'scale': [1.0, 1.0], 'path': 'C:/images/%s.png' % identity, 'srgb': effect == 'diffCol', 'color_space': '' if effect == 'diffCol' else 'raw',
             'image_channel': 'use', 'tile_u': 'repeat', 'tile_v': 'repeat', 'corrections': {'gamma': 1, 'brightness': 1, 'contrast': 1},
             '_source': {'filename': 'C:/images/%s.png' % identity, 'colorspace': '(default)', 'clip': identity}}
    layer.update(extra)
    return layer


NO_ALPHA = lambda path: False  # noqa: E731


def graph_of(made, graph=None, created=True):
    return transfer.merged(graph or nodes.new('DwaBaseMaterial', {'albedo': [.5, .5, .5]}), made, {'profile': 'modo'}, created=created)


def emitted(graph):
    lines = []
    with mock.patch.object(textures, '_prepare', lambda source, *rest, **named: str(source)), \
            mock.patch.object(textures, 'missing', lambda source: False):
        nodes.emit({'node_graph': graph, 'color': [.5] * 3}, '/test', [0], lines, {})
    return '\n'.join(lines)


MATERIAL = {'name': 'M', 'item': 'm1', 'color': [0.6, 0.5, 0.4], 'raw_color': [0.6, 0.5, 0.4], 'diffuse_amount': 1.0, 'roughness': 0.4,
            'raw_roughness': 0.4, 'shading_model': 'gtr', '_beckmann': False, '_specular_strength': 1.0, 'specular': [0.04] * 3,
            'raw_specular': [1, 1, 1], 'specular_amount': 0.04, 'metallic': 0.0, 'emission': [0, 0, 0], 'raw_emission': [1, 1, 1],
            'emission_amount': 0.0, 'ior': 1.5, 'transmission': 0, 'transmission_color': [1, 1, 1], 'refraction_roughness': 0,
            'presence': 1.0, 'clearcoat': 0, 'clearcoat_roughness': 0.01, 'bump_strength': 0.005, 'standard_material': True,
            'shader': 'DwaBaseMaterial', 'specular_fresnel': 1.0, 'reflection_fresnel': 1.0, 'layer_opacity': 1, 'layer_blend': 'normal',
            'base_layer_id': 'm1', 'material_groups': [], 'layers': [], 'subsurface_amount': 0, 'subsurface_distance': 0,
            'subsurface_color': [1, 1, 1], 'diffuse_roughness': 0, 'anisotropy': 0, 'displacement_value': 0, 'principled': False,
            'sheen': 0, 'sheen_tint': 0}


def modo_graph(layers, material=None):
    """A Modo material's plan wired as its own MoonRay text has it (transfer.marked_text, connect), as shader_tree_scene does."""
    from moonray_modo.graph import defaults_for
    material = material or MATERIAL
    made = transfer.plan('m1', layers, defaults_for(material), 'modo', {'bump_strength': .005, 'displacement_distance': .05}, NO_ALPHA)
    with mock.patch.object(textures, '_prepare', lambda source, *rest, **named: str(source)), \
            mock.patch.object(textures, 'missing', lambda source: False):
        lines = transfer.marked_text([dict(material, layers=[layer for layer in layers if layer['identity'] in made.moved])], made.keys)
    values = transfer.connect(made, 'm1', lines, '/modo/material/0')
    graph = nodes.new(made.shader, values if made.shader != 'DwaBaseMaterial' else {})
    return made, transfer.merged(graph, made, {'profile': 'modo'}, created=True), values, lines


def constant(identity, effect='diffCol', value=(1, 0, 0), **extra):
    layer = {'identity': identity, 'name': identity, 'kind': 'constant', 'effect': effect, 'value': list(value), 'opacity': 1.0,
             'blend': 'normal', 'invert': False, 'groups': [], 'texture_value': 1.0}
    layer.update(extra)
    return layer


def chain_value(lines, top):
    """The colour a chain of constant layers comes to, from the MoonRay text written for it."""
    found = transfer.objects(lines)
    return transfer.evaluate(found, ('bind', top, 1.0))


def graph_value(graph, key):
    lines = []
    with mock.patch.object(textures, '_prepare', lambda source, *rest, **named: str(source)), \
            mock.patch.object(textures, 'missing', lambda source: False):
        nodes.emit({'node_graph': graph, 'color': [.5] * 3}, '/test', [0], lines, {})
    source = graph['nodes']['surface']['inputs'][key]
    name = next(n for n in transfer.objects(lines) if n.endswith('_' + source))
    return chain_value(lines, name)


def tree_value(layers, effect='diffCol', base=(.5, .5, .5)):
    """The same layers as the Shader Tree's own drawing gives them (graph.bindings)."""
    from moonray_modo import graph
    lines = []
    material = {'color': list(base), 'raw_color': list(base), 'layers': layers, 'diffuse_amount': 1.0}
    found = graph.bindings(material, 0, lines)
    top = found[textures.EFFECTS[effect]]
    name = top.split('"')[1]
    return chain_value(lines, name)


class LayerToNodes(unittest.TestCase):
    def test_a_layer_is_one_modo_texture_node_with_its_settings(self):
        made, graph, values, _ = modo_graph([image('a', opacity=.6, blend='overlay', bias=.3, gain=.7)])
        self.assertEqual(made.moved, ['a'])
        node = made.builder.nodes['st_a_texture']
        self.assertEqual(node['type'], 'modo_texture')
        p = node['parameters']
        self.assertEqual((p['file'], p['effect'], p['blend'], p['opacity'], p['bias'], p['gain'], p['uv_map']),
                         ('C:/images/a.png', 'diffCol', 'overlay', .6, .3, .7, 'Texture'))
        self.assertEqual(node[transfer.NODE_KEY]['source']['filename'], 'C:/images/a.png')
        self.assertEqual(made.inputs['albedo'], 'st_a_texture')
        self.assertEqual(made.inputs['metallic_color'], 'st_a_texture')
        text = emitted(graph)
        self.assertIn('RemapMap(', text)
        self.assertIn('"mode"] = 8', text)

    def test_a_stack_is_a_chain_and_draws_as_the_shader_tree(self):
        layers = [constant('a', value=(1, 0, 0)), constant('b', value=(0, 1, 0), opacity=.5, blend='overlay'),
                  constant('c', value=(.2, .4, .9), opacity=.7, blend='colorburn'), constant('d', value=(.3, .3, .3), blend='softlight', invert=True)]
        made = transfer.plan('mat', layers, BASES, 'native', POST, NO_ALPHA)
        self.assertEqual(made.builder.nodes['st_d_texture']['inputs']['bg'], 'st_c_texture')
        got = graph_value(graph_of(made), 'albedo')
        want = tree_value(layers)
        for a, b in zip(got, want):
            self.assertAlmostEqual(a, b, places=9)

    def test_layer_masks_and_groups_draw_as_the_shader_tree(self):
        group = {'id': 'g', 'opacity': .5, 'blend': 'multiply', 'invert': True}
        layers = [constant('a', value=(.9, .2, .1)), constant('m', effect='layerMask', value=(.25, .25, .25), mask_target='b'),
                  constant('b', value=(.1, .8, .3), groups=[group]), constant('c', value=(.5, .5, .9), groups=[group], blend='screen')]
        made = transfer.plan('mat', layers, BASES, 'native', POST, NO_ALPHA)
        self.assertEqual(made.builder.nodes['st_b_texture']['inputs']['mask'], 'st_m_texture')
        got = graph_value(graph_of(made), 'albedo')
        want = tree_value([dict(layer, groups=layer['groups']) for layer in layers])
        for a, b in zip(got, want):
            self.assertAlmostEqual(a, b, places=9)

    def test_a_nested_masks_layers_are_laid_on_where_it_reaches_alone(self):
        outer = {'id': 'outer', 'opacity': 1, 'blend': 'normal'}
        inner = {'id': 'inner', 'opacity': 1, 'blend': 'normal'}
        layers = [constant('a', value=(.9, .2, .1)), constant('b', value=(.1, .8, .3), groups=[outer]),
                  constant('c', value=(.5, .5, .9), groups=[outer, inner])]
        scopes = {'outer': {'identity': 'outer', 'name': 'Part A', 'tag_type': 'part', 'tag': 'A', 'items': [], 'instances': False},
                  'inner': {'identity': 'inner', 'name': 'Both', 'tag_type': 'selection set', 'tag': 'S', 'items': ['mesh1'], 'instances': True}}
        made = transfer.plan('mat', layers, BASES, 'native', POST, NO_ALPHA, scopes=scopes)
        found = made.builder.nodes
        self.assertEqual(made.moved, ['a', 'b', 'c'])
        tag = found[transfer.node_id('outer', 'mask_tag')]
        self.assertEqual((tag['type'], tag['parameters']['tag']), ('modo_mask', 'A'))
        # Both a polygon tag and items: the two masks multiplied, as Modo takes both.
        self.assertIn(transfer.node_id('inner', 'mask_items'), found)
        self.assertIn(transfer.node_id('inner', 'mask_both'), found)
        # Each group is laid over what is beneath it with its mask, so overlapping ones each reach where they do.
        text = emitted(graph_of(made))
        for role in ('mask_tag', 'mask_both'):
            self.assertIn(transfer.node_id('outer' if role == 'mask_tag' else 'inner', role), text)
        # Without scopes: the same chain, no masks.
        plain = transfer.plan('mat', layers, BASES, 'native', POST, NO_ALPHA)
        self.assertFalse([n for n in plain.builder.nodes.values() if n['type'] == 'modo_mask'])

    def test_a_native_material_colour_goes_to_its_albedo(self):
        made = transfer.plan('mat', [image('a')], BASES, 'native', POST, NO_ALPHA)
        self.assertEqual(made.inputs, {'albedo': 'st_a_texture'})

    def test_every_projection_keeps_the_layers_coordinates(self):
        from moonray_modo import modo_texture
        matrix = [2.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 2.0, 0.0, 1.0, 2.0, 3.0, 1.0]
        for kind in ('uv', 'planar', 'cubic', 'spherical', 'cylindrical', 'front'):
            extra = {} if kind == 'uv' else {'uv_map': '', 'locator_matrix': matrix, 'axis': 1}
            layer = image('a', projection=kind, uv_matrix=[1.0, 0.0, .25, 0.0, 1.0, .1], rotation=.3, scale=[3.0, 2.0], **extra)
            graph = graph_of(transfer.plan('mat', [layer], BASES, 'native', POST, NO_ALPHA))
            drawn = modo_texture.layer_of(graph['nodes']['st_a_texture']['parameters'])
            want = dict(layer, coordinate_key=None)
            want['coordinate_key'] = coordinates.key(want)
            self.assertEqual(drawn['coordinate_key'], want['coordinate_key'])
            self.assertIn(drawn['coordinate_key'], [d['coordinate_key'] for d in nodes.descriptors(graph)])

    def test_roughness_goes_through_the_materials_curve_and_the_highlight_follows(self):
        made, graph, values, _ = modo_graph([image('r', effect='rough')])
        curve = graph['nodes'][made.inputs['roughness']]
        self.assertEqual(curve['type'], 'RampMap')
        self.assertEqual(curve['inputs']['input'], 'st_r_texture')
        self.assertEqual(curve['parameters']['colors'][1], [.16, .16, .16])
        self.assertEqual(graph['nodes'][made.inputs['specular']]['type'], 'modo_blend')
        nodes.validate(graph)
        self.assertIn('RampMap(', emitted(graph))

    def test_specular_and_index_of_refraction_layers_move(self):
        made, graph, values, _ = modo_graph([image('s', effect='specCol', srgb=False), image('i', effect='ior', srgb=False)])
        self.assertEqual(sorted(made.moved), ['i', 's'])
        self.assertIn('specular', made.inputs)
        nodes.validate(graph)

    def test_normals_and_bumps_of_any_number_are_one_bump_node(self):
        layers = [image('n1', effect='normal', srgb=False, image_channel='ignore'),
                  image('n2', effect='normal', srgb=False, image_channel='ignore', opacity=.5, blend='normalblend'),
                  image('b', effect='bump', srgb=False, image_channel='ignore', opacity=.5, scale=[2.0, 2.0])]
        made, graph, _, _ = modo_graph(layers)
        bump = graph['nodes'][made.inputs['input_normal']]
        self.assertEqual(bump['type'], 'bump')
        self.assertEqual(bump['inputs']['normal'], 'st_n2_texture')
        self.assertEqual(bump['inputs']['height'], 'st_b_texture')
        self.assertAlmostEqual(bump['parameters']['step'], .0005)
        text = emitted(graph)
        self.assertIn('"mode"] = 13', text)
        self.assertIn('"mode"] = 12', text)

    def test_coat_normals_drive_the_coats_own_normal(self):
        made, graph, values, _ = modo_graph([image('c', effect='normalCoat', srgb=False, image_channel='ignore')])
        self.assertEqual(graph['nodes'][made.inputs['independent_clearcoat_normal']]['type'], 'bump')
        self.assertTrue(values.get('use_independent_clearcoat_normal'))

    def test_a_displacement_is_the_graphs_displacement(self):
        made, graph, _, _ = modo_graph([image('a'), image('d', effect='displace', srgb=False)])
        self.assertEqual(sorted(made.moved), ['a', 'd'])
        node = graph['nodes'][graph['displacement']]
        self.assertEqual(node['type'], 'NormalDisplacement')
        self.assertEqual(node['inputs']['height'], 'st_d_texture')
        nodes.validate(graph)

    def test_a_subsurface_amount_mixes_the_material_with_itself(self):
        material = dict(MATERIAL, subsurface_amount=.5, subsurface_distance=.2)
        made, graph, values, _ = modo_graph([image('s', effect='subsAmt', srgb=False)], material)
        self.assertEqual(made.shader, 'DwaLayerMaterial')
        self.assertEqual(graph['nodes'][made.inputs['material_A']]['type'], 'DwaBaseMaterial')
        self.assertIn('mask', made.inputs)

    def test_a_constant_subsurface_amount_is_the_mix_by_its_value(self):
        # A plain Modo material at 60% subsurface (the plain-materials scene's Skin) was left in the Shader Tree.
        material = dict(MATERIAL, subsurface_amount=.6, subsurface_distance=.2)
        made, graph, values, _ = modo_graph([], material)
        self.assertEqual(made.shader, 'DwaLayerMaterial')
        self.assertAlmostEqual(values['mask'], .6)
        self.assertNotIn('mask', made.inputs)
        a, b = (graph['nodes'][made.inputs[part]] for part in ('material_A', 'material_B'))
        self.assertEqual((a['type'], b['type']), ('DwaBaseMaterial', 'DwaBaseMaterial'))
        self.assertGreater(a['parameters']['scattering_radius'], 0)
        self.assertEqual(b['parameters']['scattering_radius'], 0)
        nodes.validate(graph)

    def test_procedurals_through_uvs_are_baked_as_the_shader_tree_bakes_them(self):
        from moonray_modo import procedurals
        layer = image('p', kind='grid', solid_map=None, procedural={'kind': 'grid'}, path=None)
        made = transfer.plan('mat', [layer], BASES, 'native', POST, NO_ALPHA)
        self.assertEqual(made.moved, ['p'])
        with mock.patch.object(procedurals, 'bake', lambda data: ('C:/cache/p.exr', 'C:/cache/p_alpha.exr')):
            text = emitted(graph_of(made))
        self.assertIn('C:/cache/p.exr', text)

    def test_a_wireframe_is_drawn_as_the_shader_tree_draws_it(self):
        layer = constant('w', kind='wireframe', wireframe={'width': .01, 'color1': [1, 1, 1], 'color2': [0, 0, 0], 'alpha1': 1, 'alpha2': 1})
        made = transfer.plan('mat', [layer], BASES, 'native', POST, NO_ALPHA)
        self.assertIn('WireframeMap(', emitted(graph_of(made)))


class UpdateInPlace(unittest.TestCase):
    def test_a_second_run_changes_nothing(self):
        layers = [image('a'), image('b', opacity=.5, blend='multiply'), image('r', effect='rough')]
        first = graph_of(transfer.plan('mat', layers, BASES, 'native', POST, NO_ALPHA))
        again = transfer.merged(first, transfer.plan('mat', layers, BASES, 'native', POST, NO_ALPHA), {'profile': 'modo'})
        self.assertEqual(json.dumps(first, sort_keys=True), json.dumps(again, sort_keys=True))
        _, modo_first, _, _ = modo_graph(layers)
        made, _, _, _ = modo_graph(layers)
        again = transfer.merged(modo_first, made, {'profile': 'modo'})
        self.assertEqual(json.dumps(modo_first['nodes'], sort_keys=True), json.dumps(again['nodes'], sort_keys=True))

    def test_nodes_of_a_layer_that_is_gone_go_and_someone_elses_stay(self):
        first = graph_of(transfer.plan('mat', [image('a'), image('b', opacity=.5)], BASES, 'native', POST, NO_ALPHA))
        first['nodes']['mine'] = {'type': 'constant', 'parameters': {'value': [1, 0, 0]}, 'inputs': {}, 'position': [5, 5]}
        first['nodes']['surface']['inputs']['emission'] = 'mine'
        first['nodes']['st_a_texture']['position'] = [-999, 7]
        later = transfer.merged(first, transfer.plan('mat', [image('a')], BASES, 'native', POST, NO_ALPHA), {'profile': 'modo'})
        self.assertNotIn('st_b_texture', later['nodes'])
        self.assertEqual(later['nodes']['surface']['inputs']['emission'], 'mine')
        self.assertEqual(later['nodes']['surface']['inputs']['albedo'], 'st_a_texture')
        self.assertEqual(later['nodes']['st_a_texture']['position'], [-999, 7])

    def test_an_input_no_layer_drives_any_more_is_let_go(self):
        first = graph_of(transfer.plan('mat', [image('a'), image('r', effect='rough')], BASES, 'native', POST, NO_ALPHA))
        later = transfer.merged(first, transfer.plan('mat', [image('r', effect='metallic')], BASES, 'native', POST, NO_ALPHA), {'profile': 'modo'})
        inputs = later['nodes']['surface']['inputs']
        self.assertNotIn('albedo', inputs)
        self.assertEqual(inputs['metallic'], 'st_r_texture')

    def test_a_copied_node_is_not_taken_for_this_commands_own(self):
        graph = graph_of(transfer.plan('mat', [image('a')], BASES, 'native', POST, NO_ALPHA))
        graph['nodes']['node_1234'] = dict(graph['nodes']['st_a_texture'])
        later = transfer.merged(graph, transfer.Plan(), {'profile': 'modo'})
        self.assertIn('node_1234', later['nodes'])
        self.assertNotIn('st_a_texture', later['nodes'])

    def test_the_layers_records_are_found_again(self):
        graph = graph_of(transfer.plan('mat', [image('a'), constant('c')], BASES, 'native', POST, NO_ALPHA))
        found = transfer.our_layers(graph)
        self.assertEqual(found['a']['source']['clip'], 'a')
        self.assertIn('c', found)


class MoonLightIPRReading(unittest.TestCase):
    """MoonLightIPR turns Modo Texture chains back into the Shader Tree layers its compiler draws (graph_layers)."""

    def layers(self, made):
        from moonray_modo import moonlightipr_materials
        notes = []
        found = moonlightipr_materials.graph_layers({'node_graph': graph_of(made), 'native_shader': 'DwaBaseMaterial', 'native_parameters': {}},
                                                    notes.append)
        return found, notes

    def test_a_chain_is_its_layers_again(self):
        layers = [image('a'), image('b', opacity=.5, blend='softlight', bias=.3), constant('m', effect='layerMask', mask_target='c'),
                  image('c', projection='cubic', uv_map='', locator_matrix=[1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1], axis=2)]
        made = transfer.plan('mat', layers, BASES, 'native', POST, NO_ALPHA)
        found, notes = self.layers(made)
        self.assertEqual(notes, [])
        rows = [row for row in found if row.get('kind') != 'constant' or row.get('effect') == 'layerMask']
        self.assertEqual([(row['effect'], row.get('blend'), row.get('opacity')) for row in rows],
                         [('diffCol', 'normal', 1.0), ('diffCol', 'softlight', .5), ('layerMask', 'normal', 1.0), ('diffCol', 'normal', 1.0)])
        self.assertEqual(rows[1]['bias'], .3)
        self.assertEqual(rows[2]['mask_target'], rows[3]['identity'])
        self.assertEqual(rows[3]['projection'], 'cubic')

    def test_normals_beneath_a_bump_are_read_too(self):
        layers = [image('n', effect='normal', srgb=False, image_channel='ignore'), image('b', effect='bump', srgb=False, image_channel='ignore')]
        made = transfer.plan('mat', layers, BASES, 'native', POST, NO_ALPHA)
        found, notes = self.layers(made)
        self.assertEqual(sorted(row['effect'] for row in found if row.get('kind') == 'imageMap'), ['bump', 'normal'])


class ConstantValues(unittest.TestCase):
    def test_a_modo_material_is_read_back_from_its_moonray_text(self):
        from moonray_modo import moonshine, absorption
        material = {'name': 'M', 'item': 'm1', 'color': [0.6, 0.5, 0.4], 'raw_color': [0.6, 0.5, 0.4], 'diffuse_amount': 1.0, 'roughness': 0.4,
                    'raw_roughness': 0.4, 'shading_model': 'gtr', '_beckmann': False, '_specular_strength': 1.0, 'specular': [0.04] * 3,
                    'raw_specular': [1, 1, 1], 'specular_amount': 0.04, 'metallic': 0.0, 'emission': [0, 0, 0], 'raw_emission': [1, 1, 1],
                    'emission_amount': 0.0, 'ior': 1.5, 'transmission': 0, 'transmission_color': [1, 1, 1], 'refraction_roughness': 0,
                    'presence': 1.0, 'clearcoat': 0, 'clearcoat_roughness': 0.01, 'bump_strength': 0.005, 'standard_material': True,
                    'shader': 'DwaBaseMaterial', 'specular_fresnel': 1.0, 'reflection_fresnel': 1.0, 'layer_opacity': 1, 'layer_blend': 'normal',
                    'base_layer_id': 'm1', 'material_groups': [], 'layers': [], 'subsurface_amount': 0, 'subsurface_distance': 0,
                    'subsurface_color': [1, 1, 1], 'diffuse_roughness': 0, 'anisotropy': 0, 'displacement_value': 0, 'principled': False,
                    'sheen': 0, 'sheen_tint': 0}
        lines = []
        moonshine.emit_stack([absorption.surface(material)], 'st', 0, lines)
        parameters, ramps = transfer.constant_parameters(lines, '/modo/material/0')
        for got, want in zip(parameters['albedo'], [0.6, 0.5, 0.4]):
            self.assertAlmostEqual(got, want)
        self.assertAlmostEqual(parameters['roughness'], .36 + (.5 - .36) * (.05 / .15), places=6)
        self.assertAlmostEqual(parameters['specular'], 1.0)
        self.assertTrue(parameters['show_specular'])
        self.assertEqual(ramps['roughness_ramp'][1], (0.1, 0.16))
        self.assertEqual(ramps['specular_colour'], [0.04, 0.04, 0.04])

    def test_the_constant_maps_blend_as_modotexturemap_does(self):
        lines = ['ModoTextureMap("/a") {', '  ["background"] = Rgb(0.2, 0.4, 0.6),', '  ["foreground"] = Rgb(0.5, 0.5, 0.5),',
                 '  ["blend"] = 1,', '  ["opacity"] = 0.5,', '}',
                 'DwaBaseMaterial("/m") {', '  ["albedo"] = bind(ModoTextureMap("/a"), Rgb(1, 1, 1)),', '  ["roughness"] = bind(ModoTextureMap("/a"), 1),', '}']
        parameters, _ = transfer.constant_parameters(lines, '/m')
        self.assertEqual([round(v, 6) for v in parameters['albedo']], [0.15, 0.3, 0.45])
        self.assertAlmostEqual(parameters['roughness'], 0.3)


def png(path, alpha):
    rows = (b'\0' + (b'\x10\x20\x30\x40' if alpha else b'\x10\x20\x30')) * 1
    head = struct.pack('>IIBBBBB', 1, 1, 8, 6 if alpha else 2, 0, 0, 0)
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)  # noqa: E731
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', head) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


class AlphaChannels(unittest.TestCase):
    def test_headers_tell_whether_an_image_has_alpha(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            png(folder / 'a.png', True)
            png(folder / 'b.png', False)
            (folder / 'c.jpg').write_bytes(b'\xff\xd8\xff\xe0' + b'\0' * 20)
            (folder / 'd.bin').write_bytes(b'nothing known')
            self.assertIs(transfer.file_alpha(str(folder / 'a.png')), True)
            self.assertIs(transfer.file_alpha(str(folder / 'b.png')), False)
            self.assertIs(transfer.file_alpha(str(folder / 'c.jpg')), False)
            self.assertIsNone(transfer.file_alpha(str(folder / 'd.bin')))


def sub(kind, body):
    if len(body) & 1:
        body += b'\0'
    return kind + struct.pack('>H', len(body)) + body


def chns(key, value):
    body = key.encode() + b'\0'
    if len(body) & 1:
        body += b'\0'
    body += value.encode() + b'\0'
    return sub(b'CHNS', body)


def item(kind, number, *subs):
    head = kind.encode() + b'\0'
    if len(head) & 1:
        head += b'\0'
    head += b'\0\0' + struct.pack('>I', number)
    body = head + b''.join(subs)
    return b'ITEM' + struct.pack('>I', len(body)) + body + (b'\0' if len(body) & 1 else b'')


def scene(*chunks):
    body = b'LXOB' + b''.join(chunks)
    return b'FORM' + struct.pack('>I', len(body)) + body


class SceneFile(unittest.TestCase):
    def test_clips_are_read_and_the_copy_names_stand_ins(self):
        from moonray_modo import moonshine_open
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'images').mkdir()
            (folder / 'images' / 'wood.png').write_bytes(b'x')
            (folder / 'light.ies').write_bytes(b'x')
            data = scene(b'VRSN' + struct.pack('>I', 4) + b'\0\0\0\1',
                         item('videoStill', 7, chns('filename', 'images/wood.png'), chns('colorspace', 'sRGB'), chns('format', 'JPEG'),
                              sub(b'VNAM', b'wood\0')),
                         item('photometryLight', 8, chns('filename', 'light.ies')),
                         item('mesh', 9, sub(b'CHAN', b'\0\1\0\x21\0\0\0\1')))
            clips = moonshine_open.read_clips(data)
            self.assertEqual(clips, [{'number': 7, 'type': 'videoStill', 'name': 'wood', 'filename': 'images/wood.png', 'colorspace': 'sRGB',
                                      'format': 'JPEG'}])
            stand_in = folder / 'stand-in' / 'wood.png'
            copy, mapping = moonshine_open.stand_in_copy(data, folder, lambda clip: stand_in)
            self.assertEqual(struct.unpack('>I', copy[4:8])[0], len(copy) - 8)
            again = moonshine_open.read_clips(copy)
            self.assertEqual(again[0]['filename'], str(stand_in))
            self.assertEqual(again[0]['format'], 'PNG')
            self.assertEqual(again[0]['colorspace'], 'sRGB')
            self.assertEqual(mapping[str(stand_in)]['filename'], str((folder / 'images' / 'wood.png').resolve()))
            # Other files the scene names by a path from its folder are named whole in the copy, which is read elsewhere.
            self.assertIn(str((folder / 'light.ies').resolve()).encode(), copy)
            self.assertIn(b'\0\1\0\x21\0\0\0\1', copy)

    def test_a_file_named_from_a_folder_above_the_scene_is_found_as_modo_finds_it(self):
        from moonray_modo import moonshine_open
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'textures').mkdir()
            (folder / 'textures' / 'wood.png').write_bytes(b'x')
            (folder / 'scenes').mkdir()
            self.assertEqual(moonshine_open.whole('textures/wood.png', folder / 'scenes'), str((folder / 'textures' / 'wood.png').resolve()))

    def test_a_file_that_is_not_a_scene_is_refused(self):
        from moonray_modo import moonshine_open
        with self.assertRaises(moonshine_open.Unreadable):
            moonshine_open.read_clips(b'not a scene at all')

    def test_the_stand_in_is_a_png(self):
        from moonray_modo import moonshine_open
        self.assertEqual(moonshine_open.STAND_IN[:8], b'\x89PNG\r\n\x1a\n')
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 's.png'
            path.write_bytes(moonshine_open.STAND_IN)
            self.assertIs(transfer.file_alpha(str(path)), False)

    def test_the_test_scene_if_made(self):
        from moonray_modo import moonshine_open
        path = Path(__file__).resolve().parents[1] / 'test-results/shader-tree/shader_tree.lxo'
        if not path.is_file():
            self.skipTest('tools/probe_cl_shader_tree_scene.py has not made the test scene')
        data = path.read_bytes()
        clips = moonshine_open.read_clips(data)
        self.assertTrue(any(clip['filename'].endswith('colour.png') for clip in clips))
        copy, mapping = moonshine_open.stand_in_copy(data, path.parent, lambda clip: Path('C:/stand/%d/x.png' % clip['number']))
        self.assertEqual(len(mapping), len(clips))
        self.assertEqual(len(moonshine_open.read_clips(copy)), len(clips))


if __name__ == '__main__':
    unittest.main()
