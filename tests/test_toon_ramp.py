"""A toon material starts with its diffuse ramp brightest facing the light (issue 127); a MoonRay scene keeps its own."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import node_defaults, nodes

BRIGHT_FIRST = [[1.0, 1.0, 1.0], [0.75, 0.75, 0.75], [0.25, 0.25, 0.25], [0.0, 0.0, 0.0]]


class ToonRamp(unittest.TestCase):
    def test_moonray_runs_dark_to_bright(self):
        # Read at 1 - cos: position 0 faces the light. MoonRay's own default is darkest there.
        self.assertEqual(node_defaults.value(nodes.specs('DwaToonMaterial')['colors'])[0], [0.0, 0.0, 0.0])

    def test_new_toon_starts_bright_facing_the_light(self):
        self.assertEqual(node_defaults.parameters('DwaToonMaterial')['colors'], BRIGHT_FIRST)
        self.assertEqual(node_defaults.started('DwaToonMaterial', {})['colors'], BRIGHT_FIRST)
        self.assertEqual(node_defaults.start('DwaToonMaterial', 'colors', nodes.specs('DwaToonMaterial')['colors']), BRIGHT_FIRST)

    def test_a_ramp_that_was_set_is_kept(self):
        own = [[0.2, 0.2, 0.2]] * 4
        self.assertEqual(node_defaults.started('DwaToonMaterial', {'colors': own})['colors'], own)

    def test_an_imported_toon_keeps_moonray_defaults(self):
        graph = {'root': 'm', 'nodes': {'m': {'type': 'DwaToonMaterial', 'parameters': {'specular_model': 2}},
                                        'b': {'type': 'DwaBaseMaterial', 'parameters': {}}}}
        node_defaults.keep_moonray_defaults(graph)
        held = graph['nodes']['m']['parameters']
        self.assertEqual(held['colors'][0], [0.0, 0.0, 0.0])
        self.assertEqual(held['diffuse_model'], node_defaults.value(nodes.specs('DwaToonMaterial')['diffuse_model']))
        self.assertEqual(held['specular_model'], 2)
        # Only what the plugin starts otherwise is given MoonRay's own value: here glitter's reference space.
        self.assertEqual(graph['nodes']['b']['parameters'], {'glitter_space': 5})


if __name__ == '__main__':
    unittest.main()
