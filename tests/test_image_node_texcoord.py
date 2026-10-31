"""An image node from the graph editor carries its texcoord at the default, 0 0 0, among its values: the image is
then read through the mesh's UV map, not at one point of it. A texcoord typed in is still used as given. No Modo or
renderer launch."""
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import nodes, textures


def written(texcoord):
    with tempfile.TemporaryDirectory() as folder:
        texture = Path(folder) / 'image.tx'
        texture.write_bytes(b'')
        graph = nodes.new()
        parameters = {'file': str(texture), 'uv_map': 'Texture'}
        if texcoord is not None:
            parameters['texcoord'] = texcoord
        graph['nodes']['img'] = {'type': 'image', 'parameters': parameters, 'inputs': {}}
        graph['nodes']['surface']['inputs']['albedo'] = 'img'
        lines = []
        # The texture is not converted here: only how its coordinates are read is checked.
        with mock.patch.object(textures, '_prepare', lambda source, *rest: str(source)):
            nodes.emit({'node_graph': graph, 'color': [.5] * 3}, '/test', [0], lines, {})
        return '\n'.join(lines)


class ImageTexcoordTests(unittest.TestCase):
    def test_default_texcoord_reads_the_uv_map(self):
        for texcoord in (None, [0, 0, 0], [0.0, 0.0, 0.0]):
            text = written(texcoord)
            self.assertIn('AttributeMap(', text)
            self.assertNotIn('authored_uv', text)

    def test_typed_texcoord_is_kept(self):
        text = written([0.25, 0.5, 0])
        self.assertIn('authored_uv', text)
        self.assertNotIn('AttributeMap(', text)


class MissingNormalTests(unittest.TestCase):
    def written(self, image, through=None):
        graph = nodes.new()
        graph['nodes']['img'] = {'type': 'image', 'parameters': {'file': image, 'srgb': False}, 'inputs': {}}
        source = 'img'
        if through:
            graph['nodes']['between'] = {'type': through, 'parameters': {}, 'inputs': {'input': 'img'}}
            source = 'between'
        graph['nodes']['normal'] = {'type': 'normalmap', 'parameters': {'scale': 1.0}, 'inputs': {'in': source}}
        graph['nodes']['surface']['inputs']['input_normal'] = 'normal'
        lines = []
        with mock.patch.object(textures, '_prepare', lambda source, *rest: str(source)):
            nodes.emit({'node_graph': graph, 'color': [.5] * 3}, '/test', [0], lines, {})
        return '\n'.join(lines)

    def test_a_missing_image_leaves_the_normal_flat(self):
        text = self.written('V:/not/here/flakes.png')
        self.assertIn('["normal"] = Rgb(0.5, 0.5, 1)', text)
        self.assertIn('ModoNormalMap(', text)

    def test_also_through_another_node(self):
        self.assertIn('["normal"] = Rgb(0.5, 0.5, 1)', self.written('V:/not/here/flakes.png', 'ColorCorrectHsvMap'))

    def test_an_image_that_is_there_is_used(self):
        with tempfile.TemporaryDirectory() as folder:
            texture = Path(folder) / 'flakes.tx'
            texture.write_bytes(b'')
            text = self.written(str(texture))
        self.assertNotIn('Rgb(0.5, 0.5, 1)', text)
        self.assertIn('ImageMap(', text)


if __name__ == '__main__':
    unittest.main()
