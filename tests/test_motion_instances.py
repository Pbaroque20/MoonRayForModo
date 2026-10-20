"""Motion blur over copies that come and go: a copy missing at an end of the shutter is held where it is at the frame,
one there only at an end is left out, and the scene is said to have them, rather than refused (as a replicator Modo's
render cache gives fewer copies a moment from the frame was)."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo.motion import apply_motion, IDENTITY


def placed(x):
    matrix = list(IDENTITY)
    matrix[12] = x
    return matrix


def sample(copies):
    return {'camera': {'identity': 'cam', 'matrix': list(IDENTITY), 'focal_mm': 50},
            'meshes': [{'identity': 'drop', 'name': 'Drops', 'faces': [[0, 1, 2]], 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                        'material': 'm', 'instances': [placed(x) for _, x in copies], 'instance_ids': [name for name, _ in copies]}],
            'lights': []}


class CopiesThatComeAndGo(unittest.TestCase):
    def test_a_missing_copy_is_held_still(self):
        scene = sample([('a', 0.0), ('b', 1.0), ('c', 2.0)])
        apply_motion(scene, sample([('a', 0.0), ('b', 1.0), ('c', 2.0)]), sample([('a', 0.5), ('b', 1.5), ('x', 9.0)]), [-.25, .25])
        mesh = scene['meshes'][0]
        self.assertEqual(mesh['instance_ids'], ['a', 'b', 'c'])
        closing = dict(zip(mesh['instance_ids'], mesh['instances_close']))
        self.assertEqual(closing['a'][12], 0.5)
        self.assertEqual(closing['c'][12], 2.0)
        self.assertTrue(any('come and go' in w for w in scene.get('warnings', [])))

    def test_the_same_copies_say_nothing(self):
        scene = sample([('a', 0.0), ('b', 1.0)])
        apply_motion(scene, sample([('a', 0.0), ('b', 1.0)]), sample([('a', 0.5), ('b', 1.5)]), [-.25, .25])
        self.assertFalse(any('come and go' in w for w in scene.get('warnings', [])))


if __name__ == '__main__':
    unittest.main()
