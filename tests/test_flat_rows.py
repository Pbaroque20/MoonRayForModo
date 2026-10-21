import copy
import pathlib
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import evaluated, moonlightipr_scene, scene_digest


def rows(*lists):
    """Rows as Modo's geometry adapter hands them over: one block of bytes, and where each row is in it."""
    data, entries = b'', []
    for numbers, width, whole in lists:
        entries.append({'at': len(data), 'count': len(numbers) // width, 'width': width, 'whole': whole})
        data += struct.pack('<%d%s' % (len(numbers), 'i' if whole else 'f'), *numbers)
    return memoryview(data), entries


class FlatRows(unittest.TestCase):
    def mesh(self):
        held, (points, corners, sizes, normals, uvs) = rows(
            ([0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0.5], 3, False), ([0, 1, 2, 0, 2, 3], 1, True), ([3, 3], 1, True),
            ([0, 0, 1] * 6, 3, False), ([0, 0, 1, 0, 1, 1, 0, 0, 1, 1, 0, 1], 2, False))
        evaluated._new_reading()
        faces = evaluated._faces(corners, sizes, held)
        return dict(name='quad', vertices=evaluated._row(points, held), faces=faces, normals=evaluated._row(normals, held),
                    uvs=evaluated._row(uvs, held), smooth=True)

    def test_a_mesh_from_the_adapters_rows_packs_as_one_from_plain_lists(self):
        mesh = self.mesh()
        self.assertIsNotNone(scene_digest.flat(mesh['vertices']))
        self.assertIsNotNone(scene_digest.flat(mesh['faces']))
        plain = copy.deepcopy(mesh)
        self.assertIsNone(scene_digest.flat(plain['vertices']))
        moonlightipr_scene._packed.clear()
        from_rows = moonlightipr_scene.mesh_payload(mesh, {'': 0}, {'': 0})
        moonlightipr_scene._packed.clear()
        self.assertEqual(moonlightipr_scene.mesh_payload(plain, {'': 0}, {'': 0}), from_rows)

    def test_a_list_from_a_row_is_known_by_its_bytes(self):
        mesh = self.mesh()
        self.assertTrue(scene_digest.content(mesh['vertices']).startswith('row:'))
        self.assertEqual(scene_digest.content(mesh['vertices']), scene_digest.content(self.mesh()['vertices']))
        self.assertFalse(scene_digest.content(copy.deepcopy(mesh['vertices'])).startswith('row:'))


if __name__ == '__main__':
    unittest.main()
