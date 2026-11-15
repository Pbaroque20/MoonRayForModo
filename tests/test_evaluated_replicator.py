"""A replicator in Modo's render cache (evaluated.meshes): its hidden prototype, which Modo hands over at the origin with
every visibility flag off, is left out, as Modo renders nothing of it; and an item whose surfaces fall in two groups
gives meshes of different identities, which motion blur and MoonLightIPR's motion vectors need (motion.indexed)."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import evaluated, motion, rdla  # noqa: E402


def segment():
    return {'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'faces': [[0, 1, 2]], 'face_varying': True,
            'normals': [[0, 0, 1]] * 3, 'uv_sets': []}


def surface(source, item, index, instanced, visible=True, x=0.0):
    matrix = list(rdla.IDENTITY)
    matrix[12] = x
    return {'source_id': source, 'source_item': item, 'material': 'm', 'layers': [], 'visibility': [visible] * 6,
            'matrix': matrix, 'instance_index': index, 'instanced': instanced}


def data(surfaces):
    prototypes = {str(s['source_id']): {'features': [], 'segments': [segment()]} for s in surfaces}
    return {'prototypes': prototypes, 'surfaces': surfaces}


class Replicator(unittest.TestCase):
    def test_the_hidden_prototype_is_left_out(self):
        surfaces = [surface(1, 'replicator035', -1, 0, visible=False)] + [surface(1, 'replicator035', i, 1, x=i) for i in range(4)]
        meshes = evaluated.meshes(data(surfaces), {'m': {}}, [])
        self.assertEqual(len(meshes), 1)
        self.assertEqual(len(meshes[0]['instances']), 4)

    def test_one_item_s_meshes_have_their_own_identities(self):
        # A replicator of two prototypes: two groups of surfaces from one item.
        surfaces = [surface(1, 'replicator035', i, 1, x=i) for i in range(2)] + [surface(2, 'replicator035', i, 1, x=i) for i in range(2, 4)]
        meshes = evaluated.meshes(data(surfaces), {'m': {}}, [])
        self.assertEqual(len(meshes), 2)
        identities = [m['identity'] for m in meshes]
        self.assertEqual(len(set(identities)), 2)
        self.assertEqual(identities[0], 'replicator035|m|0')
        motion.indexed(meshes, 'meshes')  # no 'Motion blur requires unique meshes identities'


if __name__ == '__main__':
    unittest.main()
