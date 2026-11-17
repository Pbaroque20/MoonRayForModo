import copy
from array import array
import pathlib
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import evaluated, moonlightipr_scene, rdla, rdlb, scene_digest
from moonray_modo.rows import Rows, Faces


def rows(*lists):
    """Rows as Modo's geometry adapter hands them over: one block of bytes, and where each row is in it."""
    data, entries = b'', []
    for numbers, width, whole in lists:
        entries.append({'at': len(data), 'count': len(numbers) // width, 'width': width, 'whole': whole})
        data += struct.pack('<%d%s' % (len(numbers), 'i' if whole else 'f'), *numbers)
    return memoryview(data), entries


def plain(value):
    """Rows as the plain lists they stand for."""
    return copy.deepcopy(list(value)) if isinstance(value, Rows) else copy.deepcopy(value)


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
        plain_mesh = {key: plain(value) for key, value in mesh.items()}
        self.assertIsNone(scene_digest.flat(plain_mesh['vertices']))
        moonlightipr_scene._packed.clear()
        from_rows = moonlightipr_scene.mesh_payload(mesh, {'': 0}, {'': 0})
        moonlightipr_scene._packed.clear()
        self.assertEqual(moonlightipr_scene.mesh_payload(plain_mesh, {'': 0}, {'': 0}), from_rows)

    def test_a_list_from_a_row_is_known_by_its_bytes(self):
        mesh = self.mesh()
        self.assertTrue(scene_digest.content(mesh['vertices']).startswith('row:'))
        self.assertEqual(scene_digest.content(mesh['vertices']), scene_digest.content(self.mesh()['vertices']))
        self.assertFalse(scene_digest.content(plain(mesh['vertices'])).startswith('row:'))

    def test_rows_read_as_the_lists_they_stand_for(self):
        mesh = self.mesh()
        self.assertIsInstance(mesh['vertices'], Rows)
        self.assertIsInstance(mesh['faces'], Faces)
        self.assertEqual(mesh['vertices'], [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0.5]])
        self.assertEqual((len(mesh['vertices']), mesh['vertices'][1], mesh['vertices'][-1]), (4, [1, 0, 0], [0, 1, 0.5]))
        self.assertEqual(mesh['faces'], [[0, 1, 2], [0, 2, 3]])
        self.assertEqual((len(mesh['faces']), mesh['faces'][1], list(map(len, mesh['faces']))), (2, [0, 2, 3], [3, 3]))
        mixed = Faces(array('i', [0, 1, 2, 3, 0, 2, 3]), array('i', [4, 3]), 'mixed')
        self.assertEqual((mixed[0], mixed[1], mixed[-1], list(mixed)), ([0, 1, 2, 3], [0, 2, 3], [0, 2, 3], [[0, 1, 2, 3], [0, 2, 3]]))
        with self.assertRaises(IndexError):
            mixed[2]

    def test_rows_go_to_the_binary_scene_as_the_bytes_plain_lists_make(self):
        mesh = self.mesh()
        plain_mesh = {key: plain(value) for key, value in mesh.items()}
        written = []
        for held in (mesh, plain_mesh):
            with rdlb.collecting(fingerprints=False) as sink:
                for attribute, kind, value in (('vertex_list_0', 'vec3', held['vertices']), ('vertices_by_index', 'indices', held['faces']),
                                               ('face_vertex_count', 'counts', held['faces']), ('normal_list', 'vec3', held['normals']),
                                               ('uv_list', 'vec2', held['uvs'])):
                    rdla._heavy_line('/m', attribute, kind, value, lambda: '')
            written.append(sink.payload())
        self.assertEqual(written[0], written[1])


class Compared(unittest.TestCase):
    """Rows compared at C speed: the very same run at once, two runs of one type byte for byte, and as before otherwise
    (motion.apply_motion compared a car's meshes number by number at each end of the shutter, 7 s an update)."""

    def test_the_same_rows_are_the_same_without_reading_them(self):
        points = Rows(array('f', [0.0, 1.0, 2.0] * 4), 3, None)
        self.assertTrue(points == points)
        self.assertFalse(points != points)
        # Another Rows over the very same run.
        self.assertEqual(Rows(points.data, 3, None), points)

    def test_runs_of_one_type_are_compared_by_their_numbers(self):
        a = Rows(array('f', [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]), 3, None)
        self.assertEqual(a, Rows(array('f', [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]), 3, None))
        self.assertNotEqual(a, Rows(array('f', [0.0, 1.0, 2.0, 3.0, 4.0, 5.5]), 3, None))
        self.assertNotEqual(a, Rows(array('f', [0.0, 1.0, 2.0]), 3, None))
        self.assertNotEqual(a, Rows(array('f', [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]), 2, None))
        # Of other types, number by number as before; and against plain lists.
        self.assertEqual(a, Rows(array('d', [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]), 3, None))
        self.assertEqual(a, [[0.0, 1.0, 2.0], [3.0, 4.0, 5.0]])

    def test_faces_are_compared_by_their_corners_and_counts(self):
        quads = Faces(array('i', [0, 1, 2, 3, 4, 5, 6, 7]), array('i', [4, 4]), None)
        self.assertTrue(quads == quads)
        self.assertEqual(quads, Faces(array('i', [0, 1, 2, 3, 4, 5, 6, 7]), array('i', [4, 4]), None))
        self.assertNotEqual(quads, Faces(array('i', [0, 1, 2, 3, 4, 5, 7, 6]), array('i', [4, 4]), None))
        self.assertNotEqual(quads, Faces(array('i', [0, 1, 2, 3, 4, 5, 6, 7]), array('i', [3, 5]), None))


if __name__ == '__main__':
    unittest.main()
