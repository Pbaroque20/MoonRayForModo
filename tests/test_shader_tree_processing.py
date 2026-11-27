"""Shader Tree processing textures moved into MoonShine graphs (shader_tree_processing): Occlusion, Curvature, Gradients by
their inputs, Variation, Tension and weight maps as Modo Procedural nodes that MoonRay draws as graph.bindings draws the
layer, that the scene's scans find, and that MoonLightIPR reads back as the layer. No Modo or renderer launch."""
import json
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import graph as shader_graph, left_out, nodes, occlusion, procedurals, tension  # noqa: E402
from moonray_modo import shader_tree_processing as processing, shader_tree_transfer as transfer  # noqa: E402
from moonray_modo import moonlightipr_materials  # noqa: E402

POSITIONS = [i / 256.0 for i in range(257)]


def gradient_layer(identity, data, effect='diffCol', **extra):
    layer = {'identity': identity, 'name': identity, 'kind': 'gradient', 'effect': effect, 'opacity': 1.0, 'blend': 'normal',
             'invert': False, 'groups': [], 'uv_map': '', 'gradient': data}
    layer.update(extra)
    return layer


def ramp(low, high, alpha=None, **data):
    colours = [[low[i] + (high[i] - low[i]) * (x * x) for i in range(3)] for x in POSITIONS]
    data = dict(data, positions=list(POSITIONS), colors=colours)
    if alpha is not None:
        data['alpha'] = [alpha[0] + (alpha[1] - alpha[0]) * x ** .5 for x in POSITIONS]
    return data


def occlusion_data(alpha=None):
    data = ramp([0, 0, 0], [1, .8, .6], alpha, input='@vmap', vmap=occlusion.map_name(24, .2, .785), label='Occlusion')
    data['occlusion'] = {'rays': 24, 'distance': .2, 'spread': .785}
    return data


def moved(layer, beneath=None, base=None):
    """The graph a layer becomes as the dispatcher lays it: its foreground over the material's base value, by its
    opacity and alpha (shader_tree_transfer.laid), into the albedo."""
    builder = transfer.Builder()
    if beneath is not None:
        layer = dict(layer, _beneath=beneath)
    value, mask = processing.FOREGROUNDS[processing.key(layer)](builder, layer, layer['effect'], None)
    over = transfer.laid(builder, layer['identity'], 'over', base or ('c', [.5, .5, .5]), value, layer['blend'], layer['opacity'], [mask])
    if over[0] == 'c':
        over = builder.add('mat', 'albedo', 'constant', {'value': over[1]})
    graph = nodes.new('DwaBaseMaterial', {})
    graph['nodes'].update(builder.nodes)
    graph['nodes']['surface']['inputs']['albedo'] = over[1]
    return nodes.validate(graph)


def ramps(text):
    """Each RampMap's positions and colours, in the order written."""
    found = []
    for block in re.findall(r'RampMap\("[^"]*"\) \{(.*?)\n\}', text, re.S):
        positions = re.search(r'\["positions"\] = (\{[^}]*\})', block).group(1)
        colours = re.search(r'\["colors"\] = (\{.*?\}),\n', block, re.S).group(1)
        found.append((positions, colours))
    return found


def st_text(layer, material=None):
    lines = []
    shader_graph.bindings(dict(material or {'color': [.5, .5, .5]}, layers=[layer]), 0, lines)
    return '\n'.join(lines)


def graph_text(graph):
    lines = []
    nodes.emit({'node_graph': graph, 'color': [.5] * 3}, '/test', [0], lines, {})
    return '\n'.join(lines)


class Mapping(unittest.TestCase):
    def test_every_gradient_input_the_graph_reads_has_a_check_and_a_node(self):
        for source in ('@vmap', '@sample', '@curvature', 'diffCol', 'rough', 'diffAmt', 'driverA'):
            self.assertIn(('gradient', source), processing.CHECKS)
            self.assertIn(('gradient', source), processing.FOREGROUNDS)
        for source in ('bump', 'displace', 'groupMask'):
            self.assertNotIn(('gradient', source), processing.CHECKS)
        self.assertEqual(processing.key(gradient_layer('a', occlusion_data())), ('gradient', '@vmap'))

    def test_occlusion_draws_as_the_shader_tree_layer(self):
        layer = gradient_layer('occ', occlusion_data(alpha=(1, .3)), opacity=.7)
        graph = moved(layer)
        node = graph['nodes']['st_occ_gradient']
        self.assertEqual(node['type'], 'modo_procedural')
        self.assertEqual(len(json.loads(node['parameters']['gradient'])['positions']), 10)
        ours, theirs = graph_text(graph), st_text(layer)
        self.assertEqual(ramps(ours), ramps(theirs))
        self.assertEqual(len(ramps(ours)), 2)
        name = occlusion.map_name(24, .2, .785)
        self.assertIn('"%s"' % name, ours)

    def test_sampled_inputs_and_curvature_draw_as_the_shader_tree_layer(self):
        for data in (ramp([0, 0, 0], [1, 1, 1], input='@sample', sample='slope', span=[0.0, 3.14159], locator=[0, 0, 0]),
                     ramp([0, 0, 0], [1, 1, 1], input='@sample', sample='distance', span=[0.0, 4.0], locator=[1, 2, 3]),
                     ramp([1, 0, 0], [0, 0, 1], input='@curvature', scale=.005)):
            layer = gradient_layer('g', data)
            ours, theirs = graph_text(moved(layer)), st_text(layer)
            self.assertEqual(ramps(ours), ramps(theirs))
            for kind in ('CurvatureMap', 'TransformSpaceMap', 'AttributeMap'):
                self.assertEqual(ours.count(kind + '('), theirs.count(kind + '('), kind)

    def test_invert_is_one_less_the_gradient(self):
        layer = gradient_layer('i', ramp([0, 0, 0], [1, 1, 1], input='@curvature', scale=.005), invert=True)
        node = moved(layer)['nodes']['st_i_gradient']
        data = json.loads(node['parameters']['gradient'])
        straight = json.loads(processing.record(layer['gradient']))
        self.assertEqual(data['positions'], straight['positions'])
        for a, b in zip(data['colors'], straight['colors']):
            self.assertAlmostEqual(a[0], 1 - b[0])

    def test_a_gradient_on_a_channel_beneath_reads_its_value(self):
        layer = gradient_layer('e', ramp([0, 0, 0], [1, 1, 1], input='rough'), effect='diffCol')
        with self.assertRaises(transfer.Refused):
            moved(layer)
        constant = graph_text(moved(layer, ('c', [.3, .3, .3])))
        self.assertIn('Rgb(0.3, 0.3, 0.3)', constant)
        self.assertEqual(ramps(constant), ramps(st_text(layer, {'color': [.5] * 3, 'roughness': .3, 'raw_roughness': .3})))
        builder = transfer.Builder()
        processing.foreground(builder, dict(layer, _beneath=('n', 'st_other_image')), 'diffCol')
        self.assertEqual(builder.nodes['st_e_gradient']['inputs']['input'], 'st_other_image')

    def test_what_cannot_move_is_refused(self):
        uv = ramp([0, 0, 0], [1, 1, 1], input='@vmap', vmap='__modo_texture_uv_u_Texture_0.0_1.0',
                  texture={'axis': 0, 'uv_map': 'Texture', 'low': 0.0, 'high': 1.0})
        for layer in (gradient_layer('t', uv), gradient_layer('b', ramp([0] * 3, [1] * 3, input='bump')),
                      gradient_layer('n', occlusion_data(), effect='bump'), gradient_layer('w', ramp([0] * 3, [1] * 3, input='@vmap'))):
            with self.assertRaises(transfer.Refused):
                processing.check(layer, layer['effect'])


class Scans(unittest.TestCase):
    def materials(self, data):
        graph = moved(gradient_layer('x', data))
        return {'tag': {'node_graph': graph, 'native_shader': 'DwaBaseMaterial'}}

    def test_occlusion_tension_variation_and_weight_maps_are_found_in_graphs(self):
        found, holders = occlusion.wanted(self.materials(occlusion_data()))
        self.assertEqual(found, {occlusion.map_name(24, .2, .785): (24, .2, .785)})
        self.assertEqual(holders[occlusion.map_name(24, .2, .785)], {'tag'})
        name = tension.map_name('area', 0.0, 1.0)
        data = ramp([0] * 3, [1] * 3, input='@vmap', vmap=name, tension={'kind': 'area', 'low': 0.0, 'high': 1.0})
        self.assertEqual(tension.wanted(self.materials(data))[0], {name: ('area', 0.0, 1.0)})
        for source in (procedurals.VARIATION_MAP, procedurals.VARIATION_PART_MAP, procedurals.VARIATION_PARTICLE_MAP):
            data = ramp([0] * 3, [1] * 3, input='@vmap', vmap=source, variation={'source': 'item'})
            self.assertTrue(occlusion.reads(self.materials(data), source))
        weights = self.materials(ramp([0] * 3, [1] * 3, input='@vmap', vmap='Weights'))
        self.assertEqual(left_out.asked_vertex_maps(weights), {'Weights'})

    def test_variation_by_item_gives_the_meshes_their_numbers(self):
        snapshot = {'materials': self.materials(ramp([0] * 3, [1] * 3, input='@vmap', vmap=procedurals.VARIATION_MAP)),
                    'meshes': [{'identity': 'mesh1', 'vertices': [[0, 0, 0]] * 3}]}
        occlusion.variation(snapshot, [])
        self.assertIn(procedurals.VARIATION_MAP, snapshot['meshes'][0]['point_attributes'])


class MoonLightIPR(unittest.TestCase):
    def wired(self, layer):
        graph = moved(layer)
        found = moonlightipr_materials.graph_layers({'node_graph': graph, 'native_shader': 'DwaBaseMaterial', 'native_parameters': {}},
                                                    lambda what: self.fail(what))
        self.assertTrue(found)
        return found[-1]

    def test_a_moved_gradient_with_alpha_and_opacity_is_the_layer_again(self):
        layer = gradient_layer('occ', occlusion_data(alpha=(1, .3)), opacity=.6)
        top = self.wired(layer)
        self.assertEqual(top['kind'], 'gradient')
        self.assertEqual(top['effect'], 'diffCol')
        self.assertAlmostEqual(top['opacity'], .6)
        self.assertEqual(top['gradient']['vmap'], layer['gradient']['vmap'])
        self.assertEqual(top['gradient'], json.loads(processing.record(layer['gradient'])))
        self.assertIn('alpha', top['gradient'])

    def test_a_plain_gradient_is_the_layer_again(self):
        layer = gradient_layer('s', ramp([0] * 3, [1] * 3, input='@sample', sample='slope', span=[0.0, 3.14159], locator=[0, 0, 0]))
        top = self.wired(layer)
        self.assertEqual((top['kind'], top['opacity']), ('gradient', 1.0))
        self.assertEqual(top['gradient']['sample'], 'slope')
        self.assertNotIn('alpha', top['gradient'])


if __name__ == '__main__':
    unittest.main()
