"""Image sequences and clip choices (shader_tree_clips): which file Modo shows at a frame, the Image node's sequence
parameters and their frame's file as a scene is read, a sequence layer's nodes in Move Shader Tree Textures to MoonShine
Graphs, and layers.collect reading a sequence clip and a clip whose alpha is off. No Modo or renderer launch."""
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
for _name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(_name, types.ModuleType(_name))
from moonray_modo import nodes, shader_tree_clips as clips, shader_tree_transfer as transfer, textures  # noqa: E402

BASES = {'diffCol': [.5, .5, .5], 'rough': .4, 'metallic': 0, 'normal': [.5, .5, 1], 'groupMask': 1, 'dissolve': 0, 'lumiCol': [0, 0, 0]}
POST = {'diffuse_amount': 1.0, 'emission_amount': 1.0, 'bump_strength': .005}
NO_ALPHA = lambda path: False  # noqa: E731
SEQUENCE = {'pattern': 'C:/images/seq.[####].png', 'first_frame': 1, 'last_frame': 5, 'start_frame': 0, 'end_behavior': 'hold'}


def layer(identity='a', effect='diffCol', **extra):
    held = {'identity': identity, 'name': identity + ' (Image)', 'kind': 'imageMap', 'effect': effect, 'opacity': 1.0, 'blend': 'normal',
            'invert': False, 'groups': [], 'projection': 'uv', 'uv_map': 'Texture', 'uv_matrix': [1, 0, 0, 0, 1, 0], 'rotation': 0.0,
            'scale': [1.0, 1.0], 'path': 'C:/images/seq.0003.png', 'srgb': True, 'color_space': '', 'image_channel': 'use',
            'tile_u': 'repeat', 'tile_v': 'repeat', 'corrections': {'gamma': 1, 'brightness': 1, 'contrast': 1},
            '_source': {'pattern': SEQUENCE['pattern'], 'sequence': True}}
    held.update(extra)
    return held


def emitted(graph):
    lines = []
    with mock.patch.object(textures, '_prepare', lambda source, *rest, **named: str(source)), \
            mock.patch.object(textures, 'missing', lambda source: False):
        nodes.emit({'node_graph': graph, 'color': [.5] * 3}, '/test', [0], lines, {})
    return '\n'.join(lines)


class Frames(unittest.TestCase):
    """As Modo's own renderer showed a five-image sequence (tools/probe_cl_clip_frames.py)."""

    def shown(self, behaviour, start, frames):
        return [None if i is None else i + 1 for i in (clips.sequence_index(f, 1, 5, start, behaviour) for f in frames)]

    def test_hold_holds_the_first_and_last_files(self):
        self.assertEqual(self.shown('hold', 0, range(-2, 13)), [1, 1, 1, 2, 3, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5])
        self.assertEqual(self.shown('hold', 3, range(-2, 13)), [1, 1, 1, 1, 1, 1, 2, 3, 4, 5, 5, 5, 5, 5, 5])

    def test_repeat_runs_over_and_over_and_backwards_as_modo_has_it(self):
        self.assertEqual(self.shown('repeat', 0, range(-2, 13)), [4, 3, 1, 2, 3, 4, 5, 1, 2, 3, 4, 5, 1, 2, 3])
        self.assertEqual(self.shown('repeat', 3, range(-2, 13)), [2, 1, 5, 4, 3, 1, 2, 3, 4, 5, 1, 2, 3, 4, 5])

    def test_pingpong_turns_back_with_a_frame_of_nothing_as_modo_has_it(self):
        self.assertEqual(self.shown('pingpong', 0, range(-2, 35)),
                         [None, None, 1, 2, 3, 4, 5, 2, 1, None, 1, 2, 3, 4, 3, 2, 1, None, 1, 2, 3, 4, 3, 2, 1, None, 1, 2, 3, 4, 3, 2, 1,
                          None, 1, 2, 3])
        self.assertEqual(self.shown('pingpong', 3, range(-2, 13)), [None, None, None, None, None, 1, 2, 3, 4, 5, 2, 1, None, 1, 2])

    def test_the_pattern_names_the_frames_file(self):
        self.assertEqual(clips.pattern_file('C:/a/seq.[####].png', 7), 'C:/a/seq.0007.png')
        self.assertEqual(clips.pattern_file('C:/a/b_[##].exr', 123), 'C:/a/b_123.exr')
        self.assertEqual(clips.frame_file(SEQUENCE, 2), 'C:/images/seq.0003.png')
        self.assertEqual(clips.frame_file(dict(SEQUENCE, end_behavior='pingpong'), -1), '')


class ImageNode(unittest.TestCase):
    def node(self):
        return {'type': 'image', 'parameters': {'file': SEQUENCE['pattern'], 'sequence': True, 'first_frame': 1, 'last_frame': 5,
                                                'start_frame': 10, 'end_behavior': 'hold', 'uv_map': 'Texture'}}

    def test_a_graph_names_each_frames_file_as_it_is_read(self):
        graph = nodes.new('DwaBaseMaterial', {})
        graph['nodes']['seq'] = self.node()
        graph['nodes'][graph['root']]['inputs'] = {'albedo': 'seq'}
        nodes.validate(graph)
        at12 = clips.framed_graph(graph, 12)
        at30 = clips.framed_graph(graph, 30)
        self.assertEqual(at12['nodes']['seq']['parameters']['file'], 'C:/images/seq.0003.png')
        self.assertEqual(at30['nodes']['seq']['parameters']['file'], 'C:/images/seq.0005.png')
        self.assertEqual(graph['nodes']['seq']['parameters']['file'], SEQUENCE['pattern'])
        self.assertIn('seq.0003.png', emitted(at12))
        self.assertNotIn('[####]', emitted(at12))

    def test_a_graph_with_no_sequence_is_the_same_graph(self):
        graph = nodes.new('DwaBaseMaterial', {})
        self.assertIs(clips.framed_graph(graph, 3), graph)

    def test_an_emitted_sequence_reads_the_frame_now(self):
        graph = nodes.new('DwaBaseMaterial', {})
        graph['nodes']['seq'] = self.node()
        graph['nodes'][graph['root']]['inputs'] = {'albedo': 'seq'}
        with mock.patch.object(clips, 'scene_frame', lambda: 11):
            text = emitted(graph)
        self.assertIn('seq.0002.png', text)

    def test_the_new_parameters_leave_an_image_as_it_was(self):
        graph = nodes.new('DwaBaseMaterial', {})
        graph['nodes']['img'] = {'type': 'image', 'parameters': {'file': 'C:/images/a.png', 'uv_map': 'Texture'}}
        graph['nodes'][graph['root']]['inputs'] = {'albedo': 'img'}
        plain = emitted(graph)
        graph['nodes']['img']['parameters'].update(sequence=False, first_frame=1, last_frame=1, start_frame=0, end_behavior='hold')
        self.assertEqual(emitted(graph), plain)
        for key in clips.SEQUENCE_PARAMETERS:
            self.assertEqual(nodes.specs('image')[key]['flags'], '')

    def test_moonlightipr_reads_the_frames_file(self):
        from moonray_modo import moonlightipr_materials
        node = self.node()
        with mock.patch.object(clips, 'scene_frame', lambda: 13):
            found = moonlightipr_materials.graph_image(node)
        self.assertEqual(found['path'], 'C:/images/seq.0004.png')


class Transfer(unittest.TestCase):
    def test_a_sequence_layer_is_a_modo_texture_of_its_pattern(self):
        made = transfer.plan('mat', [layer(sequence=dict(SEQUENCE))], BASES, 'native', POST, NO_ALPHA, strict=True)
        self.assertEqual(made.moved, ['a'])
        node = made.builder.nodes['st_a_texture']
        record = json.loads(node['parameters']['layer'])
        self.assertEqual((record['sequence']['first_frame'], record['sequence']['last_frame']), (1, 5))
        graph = transfer.merged(nodes.new('DwaBaseMaterial', {}), made, {'profile': 'modo'}, created=True)
        nodes.validate(graph)
        self.assertIn('seq.0004.png', emitted(clips.framed_graph(graph, 3)))

    def test_a_pingpong_sequence_lays_nothing_where_it_shows_nothing(self):
        made = transfer.plan('mat', [layer(sequence=dict(SEQUENCE, end_behavior='pingpong'))], BASES, 'native', POST, NO_ALPHA)
        graph = transfer.merged(nodes.new('DwaBaseMaterial', {}), made, {'profile': 'modo'}, created=True)
        nodes.validate(graph)
        self.assertNotIn('ImageMap(', emitted(clips.framed_graph(graph, -1)))

    def test_a_normal_map_sequence_moves_too(self):
        made = transfer.plan('mat', [layer(effect='normal', image_channel='ignore', sequence=dict(SEQUENCE))], BASES, 'native', POST, NO_ALPHA, strict=True)
        self.assertEqual(made.moved, ['a'])

    def test_a_still_with_clip_choices_moves_with_them_recorded(self):
        made = transfer.plan('mat', [layer(sequence=None, path='C:/images/a.png', image_channel='ignore', clip_alpha='ignore',
                                           pixel_blend='nearest')], BASES, 'native', POST, lambda path: True)
        record = json.loads(made.builder.nodes['st_a_texture']['parameters']['layer'])
        self.assertEqual(record['clip_alpha'], 'ignore')
        self.assertEqual(record['pixel_blend'], 'nearest')


class Item:
    def __init__(self, identity, kind, values=None, children=(), parent=None, links=()):
        self.id, self.name, self.type = identity, identity, kind
        self.values = dict(values or {})
        self._children = list(children)
        self.parent = parent
        self._links = list(links)

    def channel(self, name):
        if name not in self.values:
            return None
        return types.SimpleNamespace(get=lambda *args, value=self.values[name]: value)

    def children(self):
        return list(self._children)

    def itemGraph(self, name):
        return types.SimpleNamespace(forward=lambda *args: list(self._links))


class Collect(unittest.TestCase):
    """layers.collect reading an image layer whose clip is a sequence, or a still whose alpha is off."""

    def read(self, clip, frame=2, **layer_values):
        import moonray_modo
        from moonray_modo import layers

        def channel(item, name, default=None):
            value = item.channel(name)
            return value.get() if value is not None else default
        host = types.ModuleType('moonray_modo.host')
        host.channel, host._CHANNELS = channel, None
        host.color = lambda item, prefix, default=(1, 1, 1): [float(channel(item, prefix + '.' + a, default[i])) for i, a in enumerate('RGB')]
        folder = Path(self.folder.name)
        locator = Item('locator', 'txtrLocator', {'projType': 'uv', 'uvMap': 'Texture', 'tileU': 'repeat', 'tileV': 'repeat'})
        values = {'enable': 1, 'render': 1, 'effect': 'diffColor', 'opacity': 1.0, 'blend': 'normal', 'alpha': 'use'}
        values.update(layer_values)
        image = Item('layer', 'imageMap', values, links=[locator, clip])
        material = Item('material', 'advancedMaterial', {'enable': 1, 'render': 1})
        render = Item('render', 'polyRender', children=[material, image])
        image.parent = material.parent = render
        scene = types.SimpleNamespace(renderItem=render, filename=str(folder / 'scene.lxo'))
        materials = {'': {'name': 'material'}}
        warnings = []
        with mock.patch.dict(sys.modules, {'moonray_modo.host': host}), mock.patch.object(moonray_modo, 'host', host, create=True), \
                mock.patch.object(clips, 'scene_frame', lambda: frame), \
                mock.patch.object(layers, 'material_tag', lambda item, texture=False: ''), \
                mock.patch('moonray_modo.group_scale.texture', lambda *args: None), \
                mock.patch('moonray_modo.texture_controls.capture', lambda *args: {}):
            layers.collect(scene, materials, warnings)
        return materials[''].get('layers', []), warnings

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        for frame in range(1, 6):
            (Path(self.folder.name) / ('seq.%04d.png' % frame)).write_bytes(b'\x89PNG\r\n\x1a\n' + bytes(frame))
        (Path(self.folder.name) / 'still.png').write_bytes(b'\x89PNG\r\n\x1a\n')

    def tearDown(self):
        self.folder.cleanup()

    def sequence(self, **extra):
        values = {'pattern': str(Path(self.folder.name) / 'seq.[####].png'), 'firstFrame': 1, 'lastFrame': 5, 'startFrame': 0,
                  'endBehavior': 'hold', 'alphaMode': 1, 'colorspace': '(default)'}
        values.update(extra)
        return Item('clip', 'videoSequence', values)

    def test_a_sequence_layer_reads_the_frames_file(self):
        found, warnings = self.read(self.sequence(), frame=2)
        self.assertEqual(len(found), 1, warnings)
        self.assertEqual(Path(found[0]['path']).name, 'seq.0003.png')
        self.assertEqual(found[0]['sequence']['end_behavior'], 'hold')
        self.assertTrue(found[0]['sequence']['pattern'].endswith('/seq.[####].png'))
        later, _ = self.read(self.sequence(), frame=40)
        self.assertEqual(Path(later[0]['path']).name, 'seq.0005.png')

    def test_a_sequence_that_shows_nothing_leaves_the_layer_out(self):
        found, warnings = self.read(self.sequence(endBehavior='pingpong'), frame=-1)
        self.assertEqual(found, [])
        self.assertTrue(any('shows no image' in w for w in warnings), warnings)

    def test_a_clip_with_its_alpha_off_is_read_as_alpha_ignored(self):
        still = Item('still', 'videoStill', {'filename': str(Path(self.folder.name) / 'still.png'), 'alphaMode': 0, 'colorspace': '(default)'})
        found, warnings = self.read(still, pixBlend='nearest')
        self.assertEqual(found[0]['image_channel'], 'ignore', warnings)
        self.assertEqual(found[0]['clip_alpha'], 'ignore')
        self.assertEqual(found[0]['pixel_blend'], 'nearest')
        self.assertNotIn('sequence', found[0])


if __name__ == '__main__':
    unittest.main()
