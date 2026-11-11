"""Modo's Gradient on Texture U and V and on Texture Value, as measured against Modo's renders
(probe_gui_gradient_uv.py, probe_gui_gradient_texture_value.py): the UV map's coordinate at each corner as a weight
(texture_uv), the locator-space coordinate under Solid and Planar (gradients.sample_signal, MoonLightIPR's row), and the
gradient read at the Value of a Constant beneath. No Modo."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))

from moonray_modo import gradients, texture_uv  # noqa: E402


class Recorder:
    def __init__(self):
        self.nodes = []

    def node(self, kind, attributes):
        self.nodes.append((kind, dict(attributes)))
        return 'node%d' % (len(self.nodes) - 1)


def rgb(value):
    values = value if isinstance(value, (list, tuple)) else [value] * 3
    return 'Rgb(%s)' % ', '.join('%g' % float(v) for v in values)


class TextureUV(unittest.TestCase):
    def scene(self, uvs, identity='m|0|Texture'):
        name = texture_uv.map_name(0, 'Texture', 0.0, 2.0)
        return name, {'materials': {'a': {'layers': [{'gradient': {'vmap': name, 'texture': {'axis': 0, 'uv_map': 'Texture', 'low': 0.0, 'high': 2.0}}}]}},
                      'meshes': [{'name': 'Plane', 'identity': identity, 'material': 'a', 'faces': [(0, 1, 2, 3)], 'uvs': uvs}]}

    def test_corners_over_the_span(self):
        name, scene = self.scene([[0, 0], [1, 0], [2, 1], [3, 1]])
        texture_uv.apply(scene, [])
        self.assertEqual([v[0] for v in scene['meshes'][0]['corner_attributes'][name]['values']], [0.0, 0.5, 1.0, 1.0])

    def test_another_uv_map_reads_zero(self):
        name, scene = self.scene([[1, 0]] * 4, identity='m|0|Other')
        warnings = []
        texture_uv.apply(scene, warnings)
        self.assertEqual(len(warnings), 1)
        self.assertEqual({v[0] for v in scene['meshes'][0]['corner_attributes'][name]['values']}, {0.0})

    def test_solid_and_planar_maps(self):
        for wrap in (False, True):
            recorder = Recorder()
            gradients.sample_signal({'sample': 'textureLocal', 'span': [-1.0, 1.0], 'locator': [1, 0, 0],
                                     'axis_vector': [0.5, 0, 0], 'wrap': wrap}, recorder.node, rgb)
            operations = [a.get('operation') for kind, a in recorder.nodes if kind == 'OpMap']
            self.assertIn('8', operations)  # along the locator's axis
            self.assertEqual('17' in operations, wrap)  # Planar wraps (x - floor x)


class TextureValue(unittest.TestCase):
    def test_gradient_at_the_value(self):
        data = {'positions': [0.0, 1.0], 'colors': [[0, 0, 0], [1, 1, 1]]}
        self.assertEqual(gradients.sample(data, 0.3), [0.3, 0.3, 0.3])


if __name__ == '__main__':
    unittest.main()
