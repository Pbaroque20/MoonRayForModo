"""Modo's Gradient on its Sample and Surface Parameters: what MoonRay is given for each (gradients.sample_signal: maps
that work the parameter out at the point, scaled from the span to 0..1), the span found where a gradient changes, and
MoonLightIPR's row for it (RAMP_SAMPLE, its settings). No Modo."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))

from moonray_modo import gradients, moonlightipr_materials as materials  # noqa: E402


class Recorder:
    def __init__(self):
        self.nodes = []

    def node(self, kind, attributes):
        self.nodes.append((kind, dict(attributes)))
        return 'node%d' % (len(self.nodes) - 1)


def rgb(value):
    values = value if isinstance(value, (list, tuple)) else [value] * 3
    return 'Rgb(%s)' % ', '.join('%g' % float(v) for v in values)


def emitted(sample, span=(0.0, 1.0), locator=(0.0, 0.0, 0.0)):
    recorder = Recorder()
    gradients.sample_signal({'sample': sample, 'span': list(span), 'locator': list(locator)}, recorder.node, rgb)
    return recorder.nodes


class SampledInputs(unittest.TestCase):
    def test_every_sampled_input_is_emitted(self):
        for sample in gradients.SAMPLED:
            with self.subTest(sample=sample):
                nodes = emitted(sample)
                # Last: the value taken as grey for the RampMap.
                self.assertEqual(nodes[-1][0], 'ModoTextureMap')

    def test_incidence_is_one_less_the_cosine_to_the_observer(self):
        kinds = [(k, a.get('map_type'), a.get('operation')) for k, a in emitted('incidenceAngle')]
        self.assertIn(('AttributeMap', '20', None), kinds)       # the way to the observer
        self.assertIn(('OpMap', None, '8'), kinds)               # dot
        self.assertIn(('OpMap', None, '1'), kinds)               # 1 less it

    def test_slope_is_the_angle_from_up(self):
        nodes = emitted('slope')
        self.assertTrue(any(k == 'OpMap' and a.get('operation') == '24' for k, a in nodes))    # acos
        self.assertTrue(any(k == 'OpMap' and a.get('op2') == 'Rgb(0, 1, 0)' for k, a in nodes))

    def test_distance_is_from_the_layers_locator(self):
        nodes = emitted('distance', locator=(1, 2, 3))
        self.assertTrue(any(k == 'OpMap' and a.get('op2') == 'Rgb(1, 2, 3)' and a.get('operation') == '1' for k, a in nodes))

    def test_scaled_from_the_span(self):
        nodes = emitted('cameraDistance', span=(2.0, 6.0))
        self.assertTrue(any(k == 'OpMap' and a.get('operation') == '1' and a.get('op2') == 'Rgb(2, 2, 2)' for k, a in nodes))
        self.assertTrue(any(k == 'OpMap' and a.get('operation') == '2' and a.get('op2') == 'Rgb(0.25, 0.25, 0.25)' for k, a in nodes))

    def test_span_where_the_gradient_changes(self):
        def ramp(x):
            return min(max(x, 0.0), 10.0)
        low, high = gradients.changing_span([ramp])
        self.assertEqual(low, 0.0)
        self.assertGreaterEqual(high, 10.0)
        self.assertLessEqual(high, 20.0)

    def test_moonlightipr_numbers_each(self):
        self.assertEqual(set(materials.SAMPLE_KINDS), set(gradients.SAMPLED) | {'textureLocal'})  # and Texture U, V by the locator
        source = (ROOT / 'moonlightipr/src/device/shared.h').read_text(encoding='utf-8')
        self.assertIn('RAMP_SAMPLE = 254', source)
        self.assertIn('SAMPLE_BACK_FACING = 11', source)


if __name__ == '__main__':
    unittest.main()
