"""A map wired to a Dwa material's metallic colour in MoonLightIPR (moonlightipr_materials.graph_layers, metallic_tint).

A tester's red metal stayed red under a texture on its Metallic Color in MoonLightIPR, while MoonRay showed the
texture: the input was left out with a notice. The uber-shader has one colour for the diffuse lobe and the metal's
reflection, albedo + (metallic colour - albedo) * metallic; the map is now laid on that colour over the albedo at the
metallic as opacity, or masked by the metallic's own image. Graphs with no such map give the same layers as before."""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_materials as materials
from moonray_modo import nodes


def material(shader, parameters, **images):
    graph = nodes.new(shader, dict(parameters))
    for key, (name, srgb) in images.items():
        graph['nodes'][name] = {'type': 'image', 'parameters': {'file': 'C:/maps/%s.png' % name, 'srgb': srgb}, 'inputs': {}}
        graph['nodes']['surface']['inputs'][key] = name
    return {'native_shader': shader, 'native_parameters': dict(parameters), 'node_graph': graph}


def layers(source):
    said = []
    return materials.graph_layers(source, said.append, None), said


RED = dict(albedo=[.8, .1, .1], metallic_color=[.8, .1, .1], roughness=.3)


class MetallicColorMap(unittest.TestCase):
    def test_wholly_metal_lays_the_map_over_the_colour(self):
        made, said = layers(material('DwaBaseMaterial', dict(RED, metallic=1.0), metallic_color=('paint', True)))
        self.assertEqual(said, [])
        self.assertEqual([(layer['effect'], layer['opacity']) for layer in made], [('diffCol', 1.0)])
        self.assertTrue(made[0]['path'].endswith('paint.png'))

    def test_half_metal_lays_it_at_half_over_the_albedo_alone(self):
        made, said = layers(material('DwaBaseMaterial', dict(RED, metallic=.5), metallic_color=('paint', True)))
        self.assertEqual(said, [])
        # The colour beneath is the albedo, not the constants' lerp, which has the metal colour in it.
        self.assertEqual(made[0]['kind'], 'constant')
        self.assertEqual(made[0]['value'], [.8, .1, .1])
        self.assertEqual((made[1]['effect'], made[1]['opacity']), ('diffCol', .5))

    def test_over_an_albedo_map_it_comes_after_it(self):
        made, said = layers(material('DwaBaseMaterial', dict(RED, metallic=.5), metallic_color=('paint', True), albedo=('wood', True)))
        self.assertEqual(said, [])
        self.assertEqual([pathlib.Path(layer['path']).stem for layer in made], ['wood', 'paint'])
        self.assertEqual([layer['opacity'] for layer in made], [1.0, .5])

    def test_a_metallic_map_masks_it(self):
        made, said = layers(material('DwaBaseMaterial', dict(RED), metallic=('metal', False), metallic_color=('paint', True)))
        self.assertEqual(said, [])
        mask = next(layer for layer in made if layer['effect'] == 'layerMask')
        tinted = next(layer for layer in made if layer['effect'] == 'diffCol' and layer.get('path', '').endswith('paint.png'))
        self.assertTrue(mask['path'].endswith('metal.png'))
        self.assertEqual(mask['mask_target'], tinted['identity'])
        self.assertLess(made.index(mask), made.index(tinted))
        # The metallic map is still the metallic channel's.
        self.assertTrue(any(layer['effect'] == 'metallic' for layer in made))

    def test_metal_material(self):
        made, said = layers(material('DwaMetalMaterial', dict(metallic_color=[.8, .1, .1], roughness=.3), metallic_color=('paint', True)))
        self.assertEqual(said, [])
        self.assertEqual([(layer['effect'], layer['opacity']) for layer in made], [('diffCol', 1.0)])

    def test_no_metal_no_tint(self):
        made, said = layers(material('DwaBaseMaterial', dict(RED, metallic=0.0), metallic_color=('paint', True)))
        self.assertEqual((made, said), ([], []))

    def test_without_the_map_nothing_changes(self):
        made, said = layers(material('DwaBaseMaterial', dict(RED, metallic=.5), albedo=('wood', True), roughness=('rough', False)))
        self.assertEqual([layer['effect'] for layer in made], ['diffCol', 'rough'])
        self.assertTrue(all(layer['opacity'] == 1.0 and layer['identity'] in ('wood', 'rough') for layer in made))

    def test_metal_colour_from_the_albedo_chain_is_still_shared(self):
        source = material('DwaBaseMaterial', dict(RED, metallic=.5), albedo=('wood', True))
        source['node_graph']['nodes']['surface']['inputs']['metallic_color'] = 'wood'
        made, said = layers(source)
        self.assertEqual((len(made), said), (1, []))


if __name__ == '__main__':
    unittest.main()
