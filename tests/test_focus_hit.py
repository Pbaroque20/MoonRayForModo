"""The surface under a point of the preview (focus.hit): its depth, as Focus Here sets it, and the mesh and face it is
on, whose material tag Select Material Here selects."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo.focus import depth, hit

CAMERA = {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1], 'film_mm': 36.0, 'focal_mm': 36.0}
# Two quads side by side at z = -5, the left one tagged 'Red', the right 'Blue'; a third behind them, tagged 'Back'.
QUADS = {'name': 'Wall', 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
         'vertices': [[-4, -4, -5], [0, -4, -5], [0, 4, -5], [-4, 4, -5], [4, -4, -5], [4, 4, -5]],
         'faces': [[0, 1, 2, 3], [1, 4, 5, 2]], 'face_materials': ['Red', 'Blue']}
BACK = {'name': 'Back', 'material': 'Back', 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
        'vertices': [[-9, -9, -9], [9, -9, -9], [9, 9, -9], [-9, 9, -9]], 'faces': [[0, 1, 2, 3]]}
SCENE = {'camera': CAMERA, 'width': 100, 'height': 100, 'meshes': [BACK, QUADS]}


class Hit(unittest.TestCase):
    def test_the_nearest_face_and_its_mesh(self):
        found = hit(SCENE, .25, .5)
        self.assertAlmostEqual(found[0], 5.0)
        self.assertIs(found[1], QUADS)
        self.assertEqual(QUADS['face_materials'][found[2]], 'Red')
        self.assertEqual(QUADS['face_materials'][hit(SCENE, .75, .5)[2]], 'Blue')

    def test_what_is_behind_where_nothing_is_in_front(self):
        scene = dict(SCENE, meshes=[BACK])
        self.assertIs(hit(scene, .5, .5)[1], BACK)
        self.assertAlmostEqual(depth(scene, .5, .5), 9.0)

    def test_nothing(self):
        self.assertIsNone(hit(dict(SCENE, meshes=[]), .5, .5))
        self.assertIsNone(depth(dict(SCENE, meshes=[]), .5, .5))


if __name__ == '__main__':
    unittest.main()
