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


def modo_graph(layers):
    """A Modo material's plan wired as its own MoonRay text has it (transfer.marked_text, connect), as shader_tree_scene does."""
    from moonray_modo.graph import defaults_for
    made = transfer.plan('m1', layers, defaults_for(MATERIAL), 'modo', {'bump_strength': .005}, NO_ALPHA)
    with mock.patch.object(textures, '_prepare', lambda source, *rest, **named: str(source)), \
            mock.patch.object(textures, 'missing', lambda source: False):
        lines = transfer.marked_text([dict(MATERIAL, layers=[layer for layer in layers if layer['identity'] in made.moved])], made.keys)
    values = transfer.connect(made, 'm1', lines, '/modo/material/0')
    return made, transfer.merged(nodes.new('DwaBaseMaterial', {}), made, {'profile': 'modo'}, created=True), values, lines


class LayerToNodes(unittest.TestCase):
    def test_a_colour_image_drives_the_colour_and_the_metal_colour(self):
        made, graph, values, _ = modo_graph([image('a')])
        self.assertEqual(made.moved, ['a'])
        self.assertEqual(made.keys, {'diffuseColor': 'st_a_image'})
        self.assertEqual(made.inputs['albedo'], 'st_a_image')
        self.assertEqual(made.inputs['metallic_color'], 'st_a_image')
        node = made.builder.nodes['st_a_image']
        self.assertEqual(node['parameters']['file'], 'C:/images/a.png')
        self.assertEqual(node[transfer.NODE_KEY]['layer'], 'a')
        self.assertTrue(values['show_specular'])
        nodes.validate(graph)
        self.assertIn('ImageMap(', emitted(graph))

    def test_a_native_material_colour_goes_to_its_albedo(self):
        made = transfer.plan('mat', [image('a')], BASES, 'native', POST, NO_ALPHA)
        self.assertEqual(made.inputs, {'albedo': 'st_a_image'})

    def test_repeats_alone_are_the_image_scale(self):
        made = transfer.plan('mat', [image('a', scale=[3.0, 2.0])], BASES, 'native', POST, NO_ALPHA)
        self.assertEqual(made.builder.nodes['st_a_image']['parameters']['scale'], [3.0, 2.0])
        self.assertNotIn('texcoord', made.builder.nodes['st_a_image']['inputs'])

    def test_a_moved_and_turned_image_reads_the_coordinates_the_layer_lays_on(self):
        layer = image('a', uv_matrix=[1, 0, .25, 0, 1, .1], rotation=.3, scale=[3.0, 2.0])
        graph = graph_of(transfer.plan('mat', [layer], BASES, 'native', POST, NO_ALPHA))
        source = graph['nodes'][graph['nodes']['st_a_image']['inputs']['texcoord']]
        self.assertEqual(source['type'], 'modo_projection')
        descriptor = nodes.projection_descriptor(source)
        for key in ('uv_matrix', 'rotation', 'scale', 'uv_map'):
            self.assertEqual(descriptor[key], layer[key])
        self.assertIn(descriptor['coordinate_key'], [d['coordinate_key'] for d in nodes.descriptors(graph)])

    def test_every_projection_is_a_modo_projection_with_the_layers_placement(self):
        matrix = [2.0, 0, 0, 0, 0, 2.0, 0, 0, 0, 0, 2.0, 0, 1, 2, 3, 1]
        for kind in ('planar', 'cubic', 'spherical', 'cylindrical', 'front'):
            layer = image('a', projection=kind, uv_map='', locator_matrix=matrix, axis=1)
            graph = graph_of(transfer.plan('mat', [layer], BASES, 'native', POST, NO_ALPHA))
            descriptor = nodes.projection_descriptor(graph['nodes']['st_a_uv'])
            self.assertEqual(descriptor['projection'], kind)
            self.assertEqual(descriptor['locator_matrix'], matrix)
            self.assertEqual(descriptor['axis'], 1)
            nodes.validate(graph)

    def test_opacity_and_blend_are_one_modo_blend(self):
        made = transfer.plan('mat', [image('a'), image('b', opacity=.5, blend='overlay')], BASES, 'native', POST, NO_ALPHA)
        top = made.builder.nodes[made.inputs['albedo']]
        self.assertEqual(top['type'], 'modo_blend')
        self.assertEqual(top['parameters'], {'blend': 9, 'opacity': .5})
        self.assertEqual((top['inputs']['bg'], top['inputs']['fg']), ('st_a_image', 'st_b_image'))
        nodes.validate(graph_of(made))

    def test_every_blend_has_its_number(self):
        from moonray_modo.layers import BLENDS
        for blend, number in BLENDS.items():
            made = transfer.plan('mat', [image('a'), image('b', blend=blend, opacity=.7)], BASES, 'native', POST, NO_ALPHA)
            self.assertEqual(made.builder.nodes[made.inputs['albedo']]['parameters']['blend'], number)
            self.assertEqual(nodes.MODO_BLENDS[number].lower().replace(' ', ''), blend)

    def test_an_image_with_alpha_is_laid_on_by_it(self):
        made = transfer.plan('mat', [image('a')], BASES, 'native', POST, lambda path: True)
        top = made.builder.nodes[made.inputs['albedo']]
        self.assertEqual(top['type'], 'modo_blend')
        self.assertEqual(top['inputs']['mask'], 'st_a_alpha')
        self.assertEqual(top['parameters']['bg'], [.5, .5, .5])
        self.assertEqual(made.builder.nodes['st_a_alpha']['parameters']['channel'], 4)

    def test_an_input_someone_wired_keeps_its_layers(self):
        made = transfer.plan('mat', [image('a'), image('r', effect='rough')], BASES, 'native', POST, NO_ALPHA, wired={'albedo'})
        self.assertEqual(made.moved, ['r'])
        self.assertIn('wires albedo', dict(made.left)['a'])

    def test_a_layer_the_graph_cannot_draw_keeps_its_effect_on_a_native_material(self):
        made = transfer.plan('mat', [image('a'), image('b', kind='wireframe'), image('r', effect='rough')], BASES, 'native', POST, NO_ALPHA)
        self.assertEqual(made.moved, ['r'])
        self.assertEqual(sorted(identity for identity, _ in made.left), ['a', 'b'])

    def test_roughness_goes_through_the_materials_curve_and_the_highlight_follows(self):
        made, graph, values, _ = modo_graph([image('r', effect='rough')])
        curve = graph['nodes'][made.inputs['roughness']]
        self.assertEqual(curve['type'], 'RampMap')
        self.assertEqual(curve['inputs']['input'], 'st_r_image')
        self.assertEqual(curve['parameters']['positions'][1], .1)
        self.assertEqual(curve['parameters']['colors'][1], [.16, .16, .16])
        specular = graph['nodes'][made.inputs['specular']]
        self.assertEqual(specular['type'], 'modo_blend')
        self.assertEqual(specular['parameters']['blend'], 5)
        nodes.validate(graph)
        self.assertIn('RampMap(', emitted(graph))

    def test_specular_layers_go_through_the_materials_fresnel_weight(self):
        made, graph, values, lines = modo_graph([image('s', effect='specCol', srgb=False)])
        self.assertIn('specular', made.inputs)
        self.assertNotIn('metallic_color', made.inputs)
        nodes.validate(graph)

    def test_a_normal_map_is_a_normal_map_node_on_its_image(self):
        made, graph, _, _ = modo_graph([image('n', effect='normal', srgb=False, image_channel='ignore')])
        normal = graph['nodes'][made.inputs['input_normal']]
        self.assertEqual(normal['type'], 'normalmap')
        self.assertEqual(normal['inputs']['in'], 'st_n_image')
        self.assertIsNotNone(nodes.normal_descriptor(normal, nodes.validate(graph)))

    def test_a_flipped_normal_map_is_turned_by_its_image(self):
        made, graph, _, _ = modo_graph([image('n', effect='normal', srgb=False, image_channel='ignore', flip_green=True)])
        normal = graph['nodes'][made.inputs['input_normal']]
        self.assertEqual(normal['inputs']['in'], 'st_n_flip_offset')
        self.assertIsNotNone(nodes.normal_descriptor(normal, nodes.validate(graph)))
        self.assertIn('"mode"] = 13', emitted(graph))

    def test_normal_and_bump_are_one_bump_node_over_the_normal_map(self):
        layers = [image('n', effect='normal', srgb=False, image_channel='ignore'),
                  image('b', effect='bump', srgb=False, image_channel='ignore', opacity=.5, scale=[2.0, 2.0])]
        made, graph, _, _ = modo_graph(layers)
        bump = graph['nodes'][made.inputs['input_normal']]
        self.assertEqual(bump['type'], 'bump')
        self.assertEqual(bump['inputs']['normal'], 'st_n_image')
        self.assertAlmostEqual(bump['parameters']['step'], .0005)
        height = graph['nodes'][bump['inputs']['height']]
        self.assertEqual(height['type'], 'modo_blend')
        text = emitted(graph)
        self.assertIn('"mode"] = 13', text)
        self.assertIn('"mode"] = 12', text)

    def test_a_solid_procedural_is_a_modo_procedural(self):
        solid = {'pattern': 0, 'type': 1, 'settings': [4.0, 2.0, .5] + [0.0] * 19 + [.5, .5], 'color1': [0, 0, 0], 'color2': [1, 1, 1],
                 'alpha1': 1.0, 'alpha2': .5, 'rows': [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]}
        layer = image('p', kind='noise', solid_map=solid, procedural=None, path=None)
        made = transfer.plan('mat', [layer], BASES, 'native', POST, NO_ALPHA)
        top = made.builder.nodes[made.inputs['albedo']]
        self.assertEqual(made.builder.nodes[top['inputs']['fg']]['type'], 'modo_procedural')
        self.assertEqual(made.builder.nodes[top['inputs']['mask']]['parameters']['output'], 1)
        text = emitted(graph_of(made))
        self.assertIn('ModoProceduralMap(', text)

    def test_a_procedural_laid_on_through_uvs_stays(self):
        layer = image('p', kind='grid', solid_map=None, procedural={'kind': 'grid'}, path=None)
        made = transfer.plan('mat', [layer], BASES, 'native', POST, NO_ALPHA)
        self.assertIn('bakes', dict(made.left)['p'])

    def test_a_displacement_layer_stays_and_holds_nothing_back(self):
        made, graph, _, _ = modo_graph([image('a'), image('d', effect='displace')])
        self.assertEqual(made.moved, ['a'])
        self.assertIn('displaces the mesh', dict(made.left)['d'])

    def test_layer_mask_and_group_are_drawn_as_the_shader_tree_does(self):
        group = {'id': 'g', 'opacity': .5, 'blend': 'normal', 'invert': True}
        mask = image('m', effect='layerMask', mask_target='b')
        made = transfer.plan('mat', [image('a'), mask, image('b', groups=[group])], BASES, 'native', POST, NO_ALPHA)
        self.assertEqual(sorted(made.moved), ['a', 'b', 'm'])
        top = made.builder.nodes[made.inputs['albedo']]
        self.assertEqual(top['parameters'], {'blend': 0, 'opacity': .5})
        inverted = made.builder.nodes[top['inputs']['fg']]
        self.assertEqual(inverted['parameters']['blend'], 3)
        inner = made.builder.nodes[inverted['inputs']['fg']]
        self.assertEqual(inner['inputs']['mask'], 'st_m_image')
        nodes.validate(graph_of(made))


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
        first['nodes']['st_a_image']['position'] = [-999, 7]
        later = transfer.merged(first, transfer.plan('mat', [image('a')], BASES, 'native', POST, NO_ALPHA), {'profile': 'modo'})
        self.assertNotIn('st_b_image', later['nodes'])
        self.assertIn('mine', later['nodes'])
        self.assertEqual(later['nodes']['surface']['inputs']['emission'], 'mine')
        self.assertEqual(later['nodes']['surface']['inputs']['albedo'], 'st_a_image')
        self.assertEqual(later['nodes']['st_a_image']['position'], [-999, 7])

    def test_an_input_no_layer_drives_any_more_is_let_go(self):
        first = graph_of(transfer.plan('mat', [image('a'), image('r', effect='rough')], BASES, 'native', POST, NO_ALPHA))
        later = transfer.merged(first, transfer.plan('mat', [image('r', effect='metallic')], BASES, 'native', POST, NO_ALPHA), {'profile': 'modo'})
        inputs = later['nodes']['surface']['inputs']
        self.assertNotIn('albedo', inputs)
        self.assertNotIn('roughness', inputs)
        self.assertEqual(inputs['metallic'], 'st_r_image')
        self.assertEqual(later[transfer.META_KEY]['inputs'], ['metallic'])

    def test_a_copied_node_is_not_taken_for_this_commands_own(self):
        graph = graph_of(transfer.plan('mat', [image('a')], BASES, 'native', POST, NO_ALPHA))
        graph['nodes']['node_1234'] = dict(graph['nodes']['st_a_image'])
        later = transfer.merged(graph, transfer.Plan(), {'profile': 'modo'})
        self.assertIn('node_1234', later['nodes'])
        self.assertNotIn('st_a_image', later['nodes'])

    def test_the_layers_records_are_found_again(self):
        graph = graph_of(transfer.plan('mat', [image('a')], BASES, 'native', POST, NO_ALPHA))
        self.assertEqual(transfer.our_layers(graph)['a']['source']['clip'], 'a')



class MoonLightIPRReading(unittest.TestCase):
    """MoonLightIPR turns the helper nodes back into the Shader Tree layers its compiler draws (graph_layers)."""

    def layers(self, made):
        from moonray_modo import moonlightipr_materials
        graph = graph_of(made)
        notes = []
        found = moonlightipr_materials.graph_layers({'node_graph': graph, 'native_shader': 'DwaBaseMaterial', 'native_parameters': {}},
                                                    notes.append)
        return found, notes

    def test_a_blend_chain_is_layers_with_their_modes(self):
        made = transfer.plan('mat', [image('a'), image('b', opacity=.5, blend='softlight')], BASES, 'native', POST, NO_ALPHA)
        found, notes = self.layers(made)
        self.assertEqual(notes, [])
        self.assertEqual([(layer['blend'], layer['opacity']) for layer in found], [('normal', 1.0), ('softlight', .5)])

    def test_a_projected_image_reads_the_layers_coordinates(self):
        layer = image('a', projection='cubic', uv_map='', locator_matrix=[1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1], axis=2)
        made = transfer.plan('mat', [layer], BASES, 'native', POST, NO_ALPHA)
        found, notes = self.layers(made)
        self.assertEqual(notes, [])
        self.assertEqual(found[0]['coordinate_key'], nodes.projection_descriptor(made.builder.nodes['st_a_uv'])['coordinate_key'])

    def test_a_solid_procedural_is_its_pattern_again(self):
        solid = {'pattern': 1, 'type': 0, 'settings': [1.0] * 22 + [.5, .5], 'color1': [1, 0, 0], 'color2': [0, 0, 1],
                 'alpha1': 1.0, 'alpha2': 1.0, 'rows': [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0]]}
        made = transfer.plan('mat', [image('p', kind='cellular', solid_map=solid, procedural=None, path=None)], BASES, 'native', POST, NO_ALPHA)
        found, notes = self.layers(made)
        self.assertEqual(notes, [])
        self.assertEqual(found[0]['solid_map']['pattern'], 1)
        self.assertEqual(found[0]['solid_map']['rows'], solid['rows'])

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
