"""The node graph's Bump node: a height image turned into a shading normal as a Shader Tree Bump layer is (MoonRay's
ModoTextureMap mode 1, then ModoNormalMap), the image read at UVs that follow the surface's (mode 12) so the bump can
read it to either side; and in MoonLightIPR the image as a bump layer at the node's amplitude. No Modo or renderer
launch."""
import re
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import nodes, textures, graph as shader_tree  # noqa: E402


def bump_graph(image, amplitude=.01, step=0.0, colour_too=False):
    graph = nodes.new()
    graph['nodes']['img'] = {'type': 'image', 'parameters': {'file': image, 'srgb': False, 'uv_map': 'Texture'}, 'inputs': {}}
    graph['nodes']['bump'] = {'type': 'bump', 'parameters': {'amplitude': amplitude, 'step': step}, 'inputs': {'height': 'img'}}
    graph['nodes']['surface']['inputs']['input_normal'] = 'bump'
    if colour_too:
        graph['nodes']['surface']['inputs']['albedo'] = 'img'
    return graph


def written(graph):
    lines = []
    with mock.patch.object(textures, '_prepare', lambda source, *rest: str(source)):
        nodes.emit({'node_graph': graph, 'color': [.5] * 3}, '/test', [0], lines, {})
    return '\n'.join(lines)


class BumpNodeTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.image = Path(self.folder.name) / 'height.tx'
        self.image.write_bytes(b'')

    def tearDown(self):
        self.folder.cleanup()

    def test_is_a_normal_node(self):
        self.assertEqual(nodes.category('bump'), 'normal')
        nodes.validate(bump_graph(str(self.image)))

    def test_writes_a_bump_into_a_normal(self):
        text = written(bump_graph(str(self.image), amplitude=.01))
        self.assertIn('["mode"] = 1', text)
        self.assertRegex(text, r'\["bump_strength"\] = 0\.01\b')
        self.assertRegex(text, r'\["height"\] = bind\(')
        self.assertIn('ModoNormalMap(', text)
        self.assertRegex(text, r'\["input_normal"\] = ModoNormalMap\(')

    def test_height_image_follows_the_surface_uvs(self):
        text = written(bump_graph(str(self.image), colour_too=True))
        self.assertIn('["mode"] = 12', text)
        self.assertIn('["uv_name"]', text)
        self.assertNotIn('AttributeMap(', text)

    def test_step_only_where_the_runtime_knows_it(self):
        held = shader_tree.BUMP_STEP
        try:
            shader_tree.BUMP_STEP = False
            self.assertNotIn('bump_step', written(bump_graph(str(self.image), step=.0005)))
            shader_tree.BUMP_STEP = True
            self.assertIn('["bump_step"] = 0.0005', written(bump_graph(str(self.image), step=.0005)))
            self.assertNotIn('bump_step', written(bump_graph(str(self.image), step=0)))
        finally:
            shader_tree.BUMP_STEP = held

    def test_a_missing_height_image_is_flat(self):
        text = written(bump_graph('V:/not/here/height.png'))
        self.assertIn('["bump_strength"] = 0', text)

    def test_override_off_leaves_it_flat(self):
        import os
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_BUMP_NODE': '0'}):
            self.assertIn('["bump_strength"] = 0', written(bump_graph(str(self.image))))
            from moonray_modo import moonlightipr_materials
            layers = moonlightipr_materials.graph_layers({'node_graph': bump_graph(str(self.image))}, lambda what: None)
            self.assertFalse([layer for layer in layers if layer.get('effect') == 'bump'])
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_BUMP_NODE': '1'}):
            self.assertRegex(written(bump_graph(str(self.image), amplitude=.01)), r'\["bump_strength"\] = 0\.01\b')

    def test_moonlightipr_reads_it_as_a_bump_layer(self):
        from moonray_modo import moonlightipr_materials
        layers = moonlightipr_materials.graph_layers({'node_graph': bump_graph(str(self.image), amplitude=.02)}, lambda what: None)
        bumps = [layer for layer in layers if layer.get('effect') == 'bump']
        self.assertEqual(len(bumps), 1)
        self.assertEqual(bumps[0]['bump_amplitude'], .02)


if __name__ == '__main__':
    unittest.main()
