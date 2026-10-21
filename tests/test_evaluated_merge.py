import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import evaluated, rdla


def segment(base, normals=True, uv=True):
    points = [[base, 0, 0], [base + 1, 0, 0], [base, 1, 0], [base + 1, 1, 0]]
    return {'vertices': points, 'faces': [[0, 1, 2], [1, 3, 2]], 'face_varying': True,
            'normals': [[0, 0, 1]] * 6 if normals else [],
            'uv_sets': [[[base, 0], [base + .5, 0], [base, .5], [base + .5, 0], [base + .5, .5], [base, .5]]] if uv else []}


def data(segments):
    return {'prototypes': {'1': {'features': [{'type': 0x54585556, 'name': 'Texture'}], 'segments': segments}},
            'surfaces': [{'source_id': 1, 'source_item': 'mesh', 'material': 'm', 'layers': [], 'visibility': [True] * 6,
                          'matrix': rdla.IDENTITY, 'instance_index': 0}]}


class EvaluatedMerge(unittest.TestCase):
    def test_a_surface_s_segments_are_one_mesh_with_the_same_polygons(self):
        values = evaluated.meshes(data([segment(0), segment(10), segment(20)]), {'m': {}}, [])
        self.assertEqual(len(values), 1)
        mesh = values[0]
        self.assertEqual(len(mesh['vertices']), 12)
        self.assertEqual(mesh['faces'], [[0, 1, 2], [1, 3, 2], [4, 5, 6], [5, 7, 6], [8, 9, 10], [9, 11, 10]])
        # Each polygon still names the same points as before.
        self.assertEqual([mesh['vertices'][i] for i in mesh['faces'][2]], [[10, 0, 0], [11, 0, 0], [10, 1, 0]])
        self.assertEqual(len(mesh['normals']), 18)
        self.assertEqual(mesh['uvs'][6], [10, 0])
        self.assertEqual(mesh['identity'].split('|')[0], 'mesh')

    def test_segments_of_different_kinds_stay_apart(self):
        values = evaluated.meshes(data([segment(0), segment(10, normals=False), segment(20)]), {'m': {}}, [])
        self.assertEqual(len(values), 2)
        self.assertEqual(sorted(len(v['vertices']) for v in values), [4, 8])
        self.assertEqual(sorted(bool(v['normals']) for v in values), [False, True])


if __name__ == '__main__':
    unittest.main()
