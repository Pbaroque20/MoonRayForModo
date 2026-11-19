"""A material row's glow is blended whole (graph.glow_whole): its Luminous Color times its Luminous Intensity. A tester's
tyre showed a white border along a soft Group Mask's edge in MoonRay where Modo blended into the material underneath:
Modo's own material there (Luminous Color white, Intensity 0) and the car's imported rubber over it (black, Intensity
1) were blended colour by colour and intensity by intensity and multiplied after, a quarter white where the mask was
half on (tools/probe_cl_group_mask_material.py with PROBE_UNDER=glow, against Modo's render)."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import graph, material_groups  # noqa: E402


def evaluate(expression, lines):
    """The value of a binding in graph.bindings' lines, for graphs of constants (ModoTextureMap blends only)."""
    nodes = {}
    text = '\n'.join(lines)
    for match in re.finditer(r'^(\w+)\("([^"]+)"\) \{\n(.*?)^\}', text, re.S | re.M):
        fields = dict(re.findall(r'\["(\w+)"\] = (.*?),?\n', match.group(3) + '\n'))
        nodes[match.group(2)] = (match.group(1), fields)

    def value(expr):
        expr = expr.strip()
        bound = re.match(r'bind\(\w+\("([^"]+)"\), .*\)$', expr)
        if bound:
            return node(bound.group(1))
        rgb = re.match(r'Rgb\(([^)]*)\)', expr)
        if rgb:
            return [float(v) for v in rgb.group(1).split(',')]
        return [float(expr)] * 3

    def node(name):
        kind, fields = nodes[name]
        assert kind == 'ModoTextureMap', kind
        background, foreground = value(fields.get('background', '0')), value(fields.get('foreground', '0'))
        mode = int(float(fields.get('blend', '0')))
        mixed = [b if mode == 0 else a * b if mode == 1 else a + b for a, b in zip(background, foreground)]
        k = float(fields.get('opacity', '1'))
        if 'mask' in fields:
            k *= sum(value(fields['mask'])) / 3
        return [a + (m - a) * k for a, m in zip(background, mixed)]
    return value(expression)


def row(name, emission, intensity, groups=(), layers=()):
    return {'name': name, 'base_layer_id': name, 'raw_color': [.5] * 3, 'color': [.5] * 3, 'diffuse_amount': .8,
            'raw_emission': list(emission), 'emission': [c * intensity for c in emission], 'emission_amount': intensity,
            'material_groups': list(groups), 'layers': list(layers)}


GROUP = {'id': 'g', 'opacity': 1, 'blend': 'normal'}
HALF = {'identity': 'mask', 'kind': 'constant', 'effect': 'groupMask', 'value': [.5] * 3, 'groups': []}


def emission(stack):
    lines = []
    result = graph.bindings(material_groups.merged(stack), 1, lines)
    expression = result.get('emissiveColor')
    return [0.0, 0.0, 0.0] if expression is None else evaluate(expression, lines)


class GlowWhole(unittest.TestCase):

    def test_two_materials_that_do_not_glow_blend_to_no_glow(self):
        glow = emission([row('Base', (1, 1, 1), 0.0), row('Rubber', (0, 0, 0), 1.0, [GROUP], [HALF])])
        for channel in glow:
            self.assertAlmostEqual(channel, 0.0)

    def test_a_glowing_material_blends_by_its_glow(self):
        # Half on: half the glowing row's colour times intensity, as Modo blends it.
        glow = emission([row('Base', (1, 1, 1), 0.0), row('Lamp', (1, .5, 0), 2.0, [GROUP], [HALF])])
        for got, want in zip(glow, (1.0, .5, 0.0)):
            self.assertAlmostEqual(got, want)

    def test_a_luminous_colour_layer_keeps_the_two_apart(self):
        layer = {'identity': 'lumi', 'kind': 'constant', 'effect': 'lumiColor', 'value': [.2] * 3, 'groups': []}
        self.assertFalse(graph.glows_whole([layer]))
        self.assertTrue(graph.glows_whole([HALF, {'kind': 'materialBase', 'effect': 'diffCol'}]))

    def test_glow_whole(self):
        defaults = {'lumiCol': [1, .5, .25], 'lumiAmt': 2.0}
        graph.glow_whole(defaults)
        self.assertEqual(defaults, {'lumiCol': [2.0, 1.0, .5], 'lumiAmt': 1})
        dark = graph.glow_whole({'lumiCol': [1, 1, 1], 'lumiAmt': 0.0})
        self.assertEqual(dark['lumiCol'], [0.0, 0.0, 0.0])


if __name__ == '__main__':
    unittest.main()
