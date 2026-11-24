"""A mesh's normals as the geometry adapter hands them over (mesh_reader.Mesh): a face with a normal of no length, or one
that is not a number (a degenerate polygon's, until Modo's Mesh Cleanup), has none, and is smoothed as a face without a
map is. Handed on, XPU2 left the scene to MoonRay XPU ("invalid normal"; a tester's car interior, intPictoMeter_geo)."""
import math
import pathlib
import struct
import sys
import unittest
from array import array

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import mesh_reader  # noqa: E402


def mesh_bytes(normals):
    """Two triangles over four points, with these corner normals (six of them)."""
    points = [0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0]
    counts, tags, subdivided, corners = [3, 3], [0, 0], [0, 0], [0, 1, 2, 0, 2, 3]
    data = b'MRM1' + struct.pack('<8i', 4, 2, 6, 0, 1, 1, 0, 0)
    data += array('f', points).tobytes() + array('i', counts).tobytes() + array('i', tags).tobytes()
    data += array('B', subdivided).tobytes() + array('i', corners).tobytes()
    data += array('B', [1, 1]).tobytes() + array('f', [v for n in normals for v in n]).tobytes()
    data += struct.pack('<i', 7) + b'Default'
    return data


class Normals(unittest.TestCase):
    def test_good_normals_are_kept(self):
        mesh = mesh_reader.Mesh(mesh_bytes([(0, 0, 1)] * 6))
        self.assertEqual(list(mesh.normal_valid), [1, 1])

    def test_a_face_with_a_normal_that_is_not_a_number_has_none(self):
        mesh = mesh_reader.Mesh(mesh_bytes([(0, 0, 1)] * 4 + [(math.nan, 0, 1), (0, 0, 1)]))
        self.assertEqual(list(mesh.normal_valid), [1, 0])
        mesh = mesh_reader.Mesh(mesh_bytes([(0, math.inf, 1)] + [(0, 0, 1)] * 5))
        self.assertEqual(list(mesh.normal_valid), [0, 1])

    def test_a_face_with_a_normal_of_no_length_has_none(self):
        mesh = mesh_reader.Mesh(mesh_bytes([(0, 0, 1)] * 3 + [(0, 0, 0)] + [(0, 0, 1)] * 2))
        self.assertEqual(list(mesh.normal_valid), [1, 0])


if __name__ == '__main__':
    unittest.main()
