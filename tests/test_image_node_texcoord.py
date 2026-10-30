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


if __name__ == '__main__':
    unittest.main()
