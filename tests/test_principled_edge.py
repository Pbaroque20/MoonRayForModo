"""Modo's Principled highlight rises toward the edge whatever its amount: a weak one (up to a specular amount of
0.125) is fitted over its whole curve, and one of none keeps a highlight; a strong one keeps the weight held to its
amount straight on."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import moonshine, rdla


def material(amount):
    return {'color': [0, 0, 0], 'raw_color': [0, 0, 0], 'specular': [amount] * 3, 'raw_specular': [1, 1, 1], 'principled': True,
            'standard_material': True, 'shader': 'DwaBaseMaterial', 'roughness': .1, 'raw_roughness': .1}


def text(amount):
    return rdla.scene_text({'camera': {'matrix': rdla.IDENTITY, 'focal_mm': 50, 'film_mm': 36},
                            'meshes': [{'name': 'ball', 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'faces': [[0, 1, 2]], 'material': 'm'}],
                            'materials': {'m': material(amount)}})


class PrincipledEdge(unittest.TestCase):
    def test_none_keeps_its_edge(self):
        written = [line for line in text(0.0).splitlines() if '"show_specular"' in line or '"specular"' in line]
        self.assertIn('  ["show_specular"] = true,', written)

    def test_the_fit_rises_toward_the_edge(self):
        lobe, weight = moonshine.principled_match(0.0, 1.0)
        import math
        edge = weight * moonshine.dielectric(math.cos(math.radians(75)), lobe)
        self.assertGreater(edge, 0.2)
        self.assertLess(weight * lobe, 0.04)


if __name__ == '__main__':
    unittest.main()
