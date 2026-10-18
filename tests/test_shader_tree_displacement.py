"""Shader Tree displacement and stencil layers: a displacement layer gives the material a NormalDisplacement, its
height times the material's Displacement Distance, and no attribute of the material; a stencil takes the surface away
where it is white, through the material's presence."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import rdla


def scene(effect, **material):
    layer = {'identity': 'layer', 'kind': 'constant', 'effect': effect, 'value': [1, 1, 1], 'opacity': 1, 'blend': 'normal', 'groups': [], 'absolute_groups': []}
    return {'camera': {'matrix': rdla.IDENTITY, 'focal_mm': 50, 'film_mm': 36},
            'meshes': [{'name': 'ball', 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'faces': [[0, 1, 2]], 'material': 'skin'}],
            'materials': {'skin': dict({'color': [.5, .5, .5], 'layers': [layer]}, **material)}}


class ShaderTreeDisplacement(unittest.TestCase):
    def test_displacement_layer_makes_a_normal_displacement(self):
        text = rdla.scene_text(scene('displace', displacement_distance=0.15))
        self.assertIn('NormalDisplacement("/modo/displacement/shader/', text)
        self.assertIn('["height_multiplier"] = 0.15', text)
        self.assertNotIn('["_displacement"]', text)

    def test_no_distance_no_displacement(self):
        self.assertNotIn('NormalDisplacement', rdla.scene_text(scene('displace', displacement_distance=0.0)))

    def test_stencil_reaches_presence(self):
        text = rdla.scene_text(scene('stencil'))
        self.assertIn('["presence"] = bind(', text)
        self.assertNotIn('["_stencil"]', text)


if __name__ == '__main__':
    unittest.main()
