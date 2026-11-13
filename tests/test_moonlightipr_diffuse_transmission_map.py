"""A map wired to DwaBase's diffuse transmission colour reaches MoonLightIPR as a layer of its own channel (28, the back:
CHANNEL_BACK in moonlightipr/src/device/shared.h), at the material's diffuse transmission amount, rather than left out.
No Modo."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))

from moonray_modo import moonlightipr_materials as materials  # noqa: E402


def material(amount=0.6):
    graph = {'version': 1, 'root': 'out', 'nodes': {
        'out': {'type': 'DwaBaseMaterial', 'parameters': {'diffuse_transmission': amount}, 'inputs': {'diffuse_transmission_color': 'img'}},
        'img': {'type': 'image', 'parameters': {'file': 'C:/leaf_trans.jpg', 'srgb': True}, 'inputs': {}}}}
    return {'node_graph': graph, 'native_parameters': {'diffuse_transmission': amount}, 'shader': 'DwaBaseMaterial'}


class DiffuseTransmissionMap(unittest.TestCase):
    def test_the_channel_matches_the_kernels(self):
        self.assertEqual(materials.CHANNELS['_backCol'], 28)
        source = (pathlib.Path(__file__).resolve().parents[1] / 'moonlightipr/src/device/shared.h').read_text(encoding='utf-8')
        self.assertIn('CHANNEL_BACK = 28', source)
        # The ocean's slope came after it (test_ocean).
        self.assertEqual(materials.CHANNELS['_slope'], 29)
        self.assertIn('CHANNEL_SLOPE = 29', source)
        self.assertIn('CHANNEL_COUNT = 30', source)

    def test_a_wired_map_is_a_layer_at_the_amount(self):
        notes = []
        layers = materials.graph_layers(material(0.6), lambda what: notes.append(what))
        self.assertEqual([layer['effect'] for layer in layers], ['_backCol'])
        self.assertAlmostEqual(layers[0]['corrections']['brightness'], 0.6)
        self.assertFalse(any('diffuse transmission' in n for n in notes))


if __name__ == '__main__':
    unittest.main()
