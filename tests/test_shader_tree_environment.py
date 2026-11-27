"""An Environment's Shader Tree layers as a MoonShine graph (shader_tree_environment): the kit reads the graph's layers
as it read the layers themselves (environments.collect gives the renderers the same environment), a run again changes
nothing, edits in the graph and in the layers are followed, and what cannot move stays with its reason. No Modo: the
scene is made of stand-in items."""
import copy
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

for name in ('lx', 'lxu', 'lxu.utils', 'lxifc', 'modo'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.modules['lxu'].utils = sys.modules['lxu.utils']
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import (environment_layout, environments, native, nodes, node_descriptions, properties,  # noqa: E402
                          shader_tree_environment as st_env, shader_tree_transfer as transfer)

IDENTITY = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0]


class Value:
    def __init__(self, value):
        self.value = value

    def get(self, *args):
        return self.value


class Links:
    def __init__(self, forward, reverse):
        self._forward, self._reverse = forward, reverse

    def forward(self, *args):
        return list(self._forward)

    def reverse(self, *args):
        return list(self._reverse)


class Item:
    def __init__(self, scene, identity, kind, name=None, channels=None, parent=None, matrix=None):
        self.scene = scene
        self.id = identity
        self.type = kind
        self.name = name or identity
        self.channels = dict(channels or {})
        self.parent = parent
        self.kids = []          # bottom first, as Modo's children()
        self.links = []
        self.tags = {}
        if matrix is not None:
            self.held_matrix = list(matrix)
        if parent is not None:
            parent.kids.append(self)  # each new layer above the last
        scene.all[identity] = self

    def channel(self, name):
        return Value(self.channels[name]) if name in self.channels else None

    def children(self):
        return list(self.kids)

    def itemGraph(self, name):
        back = [item for item in self.scene.all.values() if self in item.links] if name == 'shadeLoc' else []
        return Links(self.links if name == 'shadeLoc' else [], back)

    def readTag(self, key):
        if key not in self.tags:
            raise LookupError(key)
        return self.tags[key]

    def hasTag(self, key):
        return key in self.tags

    def setTag(self, key, value):
        self.tags[key] = value


class Scene:
    def __init__(self):
        self.all = {}
        self.filename = None
        self.renderItem = Item(self, 'render', 'polyRender', 'Render', {'globEnable': 1})
        self.environment = Item(self, 'env', 'environment', 'Environment', {'radiance': 1.0}, self.renderItem)

    def items(self, kind, superType=True):
        return [item for item in self.all.values() if item.type == kind]

    def item(self, identity):
        if identity not in self.all:
            raise LookupError(identity)
        return self.all[identity]


def colour(prefix, rgb):
    return {prefix + '.' + axis: v for axis, v in zip('RGB', rgb)}


LAYER = {'enable': True, 'render': True, 'opacity': 1.0, 'blend': 'normal', 'invert': False, 'effect': 'envColor'}
LOCATOR = {'projType': 'spherical', 'projAxis': 1, 'wrapU': 1.0, 'wrapV': 1.0, 'uvRotation': 0.0, 'tileU': 'repeat', 'tileV': 'repeat',
           'triplanarBlending': 0.0, 'randOffset': 'none', 'm00': 1.0, 'm01': 0.0, 'm02': 0.0, 'm10': 0.0, 'm11': 1.0, 'm12': 0.0}


def sky(scene, name='Environment Material', **extra):
    channels = dict(LAYER, type='grad4', skyExp=4.0, gndExp=2.0, **colour('zenColor', (.1, .2, .6)), **colour('skyColor', (.7, .8, 1)),
                    **colour('gndColor', (.3, .3, .2)), **colour('nadColor', (.1, .1, .1)))
    channels.update(extra)
    return Item(scene, 'sky', 'envMaterial', name, channels, scene.environment)


def image(scene, identity, path, projection='spherical', matrix=IDENTITY, **extra):
    clip = Item(scene, identity + '_clip', 'videoStill', Path(path).name, {'filename': str(path), 'colorspace': '(default)'})
    locator = Item(scene, identity + '_loc', 'txtrLocator', identity + ' locator', dict(LOCATOR, projType=projection), matrix=matrix)
    channels = dict(LAYER, gamma=1.0, brightness=1.0, contrast=1.0, min=0.0, max=1.0, swizzling=False, rgba='use', alpha='use',
                    redInv=False, greenInv=False, blueInv=False)
    channels.update(extra)
    layer = Item(scene, identity, 'imageMap', identity + ' (Image)', channels, scene.environment)
    layer.links = [locator, clip]
    return layer, locator, clip


def constant(scene, identity, rgb, **extra):
    return Item(scene, identity, 'constant', identity, dict(LAYER, **colour('color', rgb), **extra), scene.environment)


def grid(scene, identity, **extra):
    locator = Item(scene, identity + '_loc', 'txtrLocator', identity + ' locator', dict(LOCATOR), matrix=IDENTITY)
    channels = dict(LAYER, type='square', lineWidth=.1, transWidth=.05, bias=.5, gain=.5, alpha1=1.0, alpha2=1.0,
                    **colour('color1', (0, 0, 0)), **colour('color2', (1, .5, .2)))
    channels.update(extra)
    layer = Item(scene, identity, 'grid', identity, channels, scene.environment)
    layer.links = [locator]
    return layer, locator


def plain(environments_found):
    """The renderers' environments, without the identities of the layers read (a stand-in's, after the move)."""
    found = copy.deepcopy(environments_found)

    def strip(value):
        if isinstance(value, dict):
            value.pop('layer_identity', None)
            for v in value.values():
                strip(v)
        elif isinstance(value, list):
            for v in value:
                strip(v)
    strip(found)
    return json.loads(json.dumps(found, sort_keys=True))


class Harness(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.hdr = Path(self.folder.name) / 'sky.hdr'
        self.hdr.write_bytes(b'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 1 +X 2\n' + bytes(8))
        self.scene = Scene()
        self.evals = []
        patches = [mock.patch.object(environment_layout, 'image', side_effect=OSError('no image tool in the tests')),
                   mock.patch.object(native, 'environment_projections', lambda: True),
                   mock.patch.object(properties, 'write', self.write),
                   mock.patch.object(sys.modules['lx'], 'eval', self.eval, create=True)]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def write(self, item, values):
        item.setTag(properties.TAG, json.dumps(values, sort_keys=True, separators=(',', ':')))

    def eval(self, command):
        self.evals.append(command)
        if command.startswith('item.channel textureLayer$enable '):
            _, _, value, target = command.split(' ')
            self.scene.item(target[len('item:{'):-1]).channels['enable'] = value == 'true'
        elif command.startswith('select.item ') or command == '!item.delete':
            if command == '!item.delete':
                held = self.selected
                for item in self.scene.all.values():
                    if held in item.links:
                        item.links.remove(held)
                del self.scene.all[held.id]
            else:
                self.selected = self.scene.item(command.split('{')[1].split('}')[0])
        else:
            raise AssertionError('unexpected command ' + command)

    def collected(self):
        return environments.collect(self.scene, [])

    def run_command(self):
        from moonray_modo import shader_tree_scene
        report = shader_tree_scene.Report()
        freed = st_env.run(self.scene, report)
        shader_tree_scene.unload(self.scene, set(freed), dict(freed), report)
        return report, freed

    def graph(self):
        return properties.read(self.scene.environment).get(st_env.KEY)


class Moves(Harness):
    def test_an_hdri_moves_and_renders_the_same(self):
        layer, _, clip = image(self.scene, 'hdri', self.hdr)
        before = self.collected()
        self.assertEqual(before[0]['kind'], 'image')
        report, freed = self.run_command()
        self.assertEqual(set(freed), {'hdri'})
        self.assertFalse(layer.channels['enable'])
        self.assertNotIn(clip.id, self.scene.all)
        self.assertEqual(report.unloaded, ['sky.hdr'])
        after = self.collected()
        self.assertEqual(plain(after), plain(before))
        # Named as the layer was, so that the composed picture is the one cached for the layer; never the layer itself.
        self.assertEqual(json.dumps(after, sort_keys=True), json.dumps(before, sort_keys=True))
        self.assertNotEqual(after[0]['layer_identity'], 'hdri')
        self.assertEqual(str(after[0]['layer_identity']), 'hdri')
        self.assertEqual(copy.deepcopy(after[0]['layer_identity']), after[0]['layer_identity'])
        graph = self.graph()
        self.assertEqual(graph['nodes']['environment']['inputs'], {'color': 'st_hdri_over'})
        node = graph['nodes']['st_hdri_image']
        self.assertEqual(node['type'], st_env.IMAGE)
        self.assertEqual(node[transfer.NODE_KEY]['layer'], 'hdri')
        self.assertEqual(node[transfer.NODE_KEY]['source']['filename'], str(self.hdr))
        self.assertTrue(all(transfer.ours(i, n) for i, n in graph['nodes'].items() if i != 'environment'))

    def test_a_gradient_an_image_by_a_blend_a_colour_and_a_grid_render_the_same(self):
        sky(self.scene)
        image(self.scene, 'hdri', self.hdr, opacity=.6, blend='multiply')
        grid(self.scene, 'grid', opacity=.3)
        constant(self.scene, 'tint', (.2, .1, 0), blend='add', opacity=.5)
        before = self.collected()
        self.assertEqual([layer['kind'] for layer in before[0]['layers']], ['color', 'procedural', 'image', 'grad4'])
        report, freed = self.run_command()
        self.assertEqual(set(freed), {'sky', 'hdri', 'grid', 'tint'})
        self.assertEqual(plain(self.collected()), plain(before))
        graph = self.graph()
        self.assertEqual(graph['nodes']['st_hdri_over']['parameters'], {'blend': 1, 'opacity': .6})
        self.assertEqual(graph['nodes']['st_hdri_over']['inputs'], {'fg': 'st_hdri_image', 'bg': 'st_sky_over'})
        self.assertEqual(graph['nodes']['st_tint_over']['parameters']['fg'], [.2, .1, 0])
        self.assertEqual(graph['nodes']['st_sky_sky']['type'], st_env.SKY)
        self.assertEqual(graph['nodes']['st_grid_procedural']['parameters']['kind'], 'grid')
        self.assertEqual(len(report.moved), 4)

    def test_another_projection_renders_the_same(self):
        sky(self.scene)
        turned = [0.0, 0, -2.0, 0, 0, 2.0, 0, 0, 2.0, 0, 0, 0, 0, 0, 0, 1.0]
        image(self.scene, 'cube', self.hdr, projection='cubic', matrix=turned, opacity=.8)
        before = self.collected()
        self.assertEqual(before[0]['layers'][0]['projection']['projection'], 'cubic')
        self.run_command()
        self.assertEqual(plain(self.collected()), plain(before))
        self.assertEqual(self.graph()['nodes']['st_cube_image']['parameters']['projection'], 'cubic')

    def test_the_locator_still_places_the_image_and_the_nodes_numbers_when_it_is_gone(self):
        _, locator, _ = image(self.scene, 'hdri', self.hdr, projection='cubic')
        self.run_command()
        locator.held_matrix = [0.0, 0, -1.0, 0, 0, 1.0, 0, 0, 1.0, 0, 0, 0, 0, 0, 0, 1.0]
        turned = self.collected()
        self.assertEqual(turned[0]['layers'][0]['matrix'], locator.held_matrix)
        del self.scene.all[locator.id]
        self.assertEqual(self.collected()[0]['layers'][0]['matrix'], IDENTITY)

    def test_a_run_again_changes_nothing(self):
        sky(self.scene)
        image(self.scene, 'hdri', self.hdr, opacity=.5)
        self.run_command()
        tag = self.scene.environment.tags[properties.TAG]
        commands = len(self.evals)
        report, _ = self.run_command()
        self.assertEqual(self.scene.environment.tags[properties.TAG], tag)
        self.assertEqual(len(self.evals), commands)
        self.assertEqual(report.lines()[1], 'Nothing changed: every graph is up to date with its layers.')

    def test_edits_in_the_graph_are_drawn_and_kept_by_a_run_again(self):
        sky(self.scene)
        image(self.scene, 'hdri', self.hdr, opacity=.5)
        self.run_command()
        graph = self.graph()
        graph['nodes']['st_hdri_over']['parameters']['opacity'] = .25
        graph['nodes']['st_hdri_image']['parameters']['gamma'] = 2.2
        properties.write(self.scene.environment, dict(properties.read(self.scene.environment), **{st_env.KEY: graph}))
        drawn = self.collected()[0]['layers'][0]
        self.assertEqual(drawn['opacity'], .25)
        self.assertEqual(drawn['corrections']['gamma'], 2.2)
        self.run_command()
        self.assertEqual(self.graph()['nodes']['st_hdri_over']['parameters']['opacity'], .25)
        self.assertEqual(self.graph()['nodes']['st_hdri_image']['parameters']['gamma'], 2.2)

    def test_an_edit_of_a_moved_layer_is_followed_by_a_run_again(self):
        sky(self.scene)
        layer, _, _ = image(self.scene, 'hdri', self.hdr, opacity=.5)
        self.run_command()
        layer.channels['opacity'] = .75
        report, _ = self.run_command()
        self.assertEqual(self.graph()['nodes']['st_hdri_over']['parameters']['opacity'], .75)
        self.assertEqual(report.updated, ['Environment'])
        self.assertFalse(layer.channels['enable'])
        # The layer reads its image back from its node: its clip is gone.
        self.assertEqual(self.graph()['nodes']['st_hdri_image']['parameters']['file'], str(self.hdr))

    def test_a_new_layer_is_moved_and_a_deleted_one_taken_out(self):
        sky(self.scene)
        image(self.scene, 'hdri', self.hdr, opacity=.5)
        self.run_command()
        constant(self.scene, 'tint', (.3, .3, .3), opacity=.5)
        warnings = []
        environments.collect(self.scene, warnings)
        self.assertTrue(any('tint is on in the Shader Tree' in w for w in warnings))
        del self.scene.all['hdri']
        self.scene.environment.kids = [k for k in self.scene.environment.kids if k.id != 'hdri']
        report, _ = self.run_command()
        self.assertEqual(sorted(i for i in self.graph()['nodes'] if i != 'environment'), ['st_sky_over', 'st_sky_sky', 'st_tint_over'])
        self.assertEqual(report.removed_nodes, 2)

    def test_a_layer_in_a_group_keeps_the_environment_in_the_shader_tree(self):
        sky(self.scene)
        group = Item(self.scene, 'group', 'mask', 'Group', {'enable': True, 'render': True, 'opacity': 1.0, 'blend': 'normal'}, self.scene.environment)
        layer, _, clip = image(self.scene, 'hdri', self.hdr)
        self.scene.environment.kids.remove(layer)
        group.kids.insert(0, layer)
        layer.parent = group
        report, freed = self.run_command()
        self.assertEqual(freed, {})
        self.assertIsNone(self.graph())
        self.assertIn(clip.id, self.scene.all)
        self.assertEqual(report.left, [('Environment', 'its layer hdri (Image) is in a group, which the graph does not lay')])

    def test_an_environment_that_cannot_move_any_more_has_its_layers_put_back(self):
        sky(self.scene)
        layer, _, _ = image(self.scene, 'hdri', self.hdr)
        self.run_command()
        group = Item(self.scene, 'group', 'mask', 'Group', {'enable': True, 'render': True, 'opacity': 1.0, 'blend': 'normal'}, self.scene.environment)
        tint = constant(self.scene, 'tint', (.5, .5, .5), opacity=.5)
        self.scene.environment.kids.remove(tint)
        group.kids.append(tint)
        tint.parent = group
        restored = []
        from moonray_modo import shader_tree_scene
        with mock.patch.object(shader_tree_scene, 'restore', lambda scene, item, source: restored.append((item.id, source['filename'])) or True):
            report, _ = self.run_command()
        self.assertEqual(restored, [('hdri', str(self.hdr))])
        self.assertTrue(self.scene.item('sky').channels['enable'])
        self.assertIsNone(self.graph())
        self.assertIn('hdri (Image)', report.restored)

    def test_a_layer_the_kit_does_not_read_stays_with_its_reason(self):
        sky(self.scene)
        image(self.scene, 'hdri', self.hdr, opacity=.5)
        image(self.scene, 'random', self.hdr)
        self.scene.item('random_loc').channels['randOffset'] = 'random'
        self.scene.item('random').links[1] = self.scene.item('hdri_clip')  # the same clip as hdri's
        report, freed = self.run_command()
        self.assertEqual(set(freed), {'sky', 'hdri'})
        self.assertIn(('sky.hdr', 'also used by random (Image)'), report.kept)
        self.assertIn(('random (Image)', 'environment random offsets are unsupported'), report.left)
        self.assertTrue(self.scene.item('random').channels['enable'])
        # Its clip is used by the layer that stays: kept.
        self.assertIn('hdri_clip', self.scene.all)
        warnings = []
        environments.collect(self.scene, warnings)
        self.assertFalse(any('random (Image) is on' in w for w in warnings))

    def test_an_environment_without_an_image_is_left_as_it_is_unless_asked(self):
        sky(self.scene)
        constant(self.scene, 'tint', (.2, .2, .2), opacity=.5)
        before = self.collected()
        report, freed = self.run_command()
        self.assertEqual((freed, self.graph(), report.left), ({}, None, []))
        with mock.patch.object(st_env, 'WITHOUT_IMAGES', True):
            report, freed = self.run_command()
        self.assertEqual(set(freed), {'sky', 'tint'})
        self.assertEqual(json.dumps(self.collected(), sort_keys=True), json.dumps(before, sort_keys=True))


class Nodes(unittest.TestCase):
    def test_the_environment_nodes_are_modo_shader_tree_nodes_with_descriptions(self):
        for kind in nodes.ENVIRONMENT_NODES:
            self.assertIn(kind, nodes.MODO_NODES)
            self.assertIn(kind, node_descriptions.DESCRIPTIONS)
            schema = nodes.specs(kind)
            for key, spec in schema.items():
                self.assertEqual(spec['default_value'], nodes.MAPS[kind][key][1])
        self.assertTrue(nodes.connectable('modo_environment', 'color'))
        self.assertFalse(nodes.connectable(st_env.IMAGE, 'file'))

    def test_a_surface_graph_refuses_an_environment_node(self):
        graph = nodes.new('DwaBaseMaterial', {})
        graph['nodes']['sky'] = {'type': st_env.SKY, 'parameters': {}, 'inputs': {}}
        graph['nodes']['surface']['inputs']['albedo'] = 'sky'
        with self.assertRaises(ValueError):
            nodes.emit({'node_graph': graph}, '/test', [0], [], {})

    def test_a_hand_made_graph_is_drawn(self):
        scene = Scene()
        graph = {'version': 1, 'root': 'out', 'nodes': {
            'out': {'type': 'modo_environment', 'parameters': {}, 'inputs': {'color': 'over'}},
            'over': {'type': 'modo_blend', 'parameters': {'blend': 2, 'opacity': .5, 'bg': [.1, .1, .1]}, 'inputs': {'fg': 'gradient'}},
            'gradient': {'type': st_env.SKY, 'parameters': {'type': 'grad2'}, 'inputs': {}}}}
        scene.environment.setTag(properties.TAG, json.dumps({st_env.KEY: graph}))
        found = environments.collect(scene, [])
        self.assertEqual([(layer['kind'], layer['blend'], layer['opacity']) for layer in found[0]['layers']],
                         [('grad2', 'add', .5), ('color', 'normal', 1.0)])

    def test_a_broken_graph_is_said_and_drawn_black(self):
        scene = Scene()
        graph = {'version': 1, 'root': 'out', 'nodes': {'out': {'type': 'modo_environment', 'parameters': {}, 'inputs': {'color': 'gone'}}}}
        scene.environment.setTag(properties.TAG, json.dumps({st_env.KEY: graph}))
        warnings = []
        self.assertEqual(environments.collect(scene, warnings), [])
        self.assertTrue(any('cannot be drawn' in w for w in warnings))


if __name__ == '__main__':
    unittest.main()
