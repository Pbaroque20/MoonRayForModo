"""Subdivision creases read by the geometry adapter (native-modo/subdivision_creases.cpp, host.creases_natively): the
faces handed over flat, the weights given back made MoonRay's sharpness as the reading in Python makes them (a weight
of 1 or more a sharpness of 10), and None (the reading in Python) where the adapter has no such reader."""
import ast
import ctypes
import sys
import types
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo/python'
sys.path.insert(0, str(KIT))
from moonray_modo import rows  # noqa: E402


def wrapper(bridge):
    """host.creases_natively, run outside Modo with the adapter given."""
    source = (KIT / 'moonray_modo/host.py').read_text(encoding='utf-8')
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'creases_natively')
    for statement in ast.walk(node):
        if isinstance(statement, ast.ImportFrom) and statement.module is None:
            statement.names = [a for a in statement.names if a.name not in ('mesh_reader', 'rows')]
    node.body = [s for s in node.body if not (isinstance(s, ast.ImportFrom) and not s.names)]
    space = {'mesh_reader': types.SimpleNamespace(bridge=lambda: bridge), 'rows': rows}
    exec(compile(ast.Module(body=[node], type_ignores=[]), 'host.py', 'exec'), space)
    return space['creases_natively']


class Mesh:
    def __peekobj__(self):
        return 1234


class Adapter:
    """MR_subdivision_creases as a stand-in: the faces it was handed, and two creases and a corner given back."""

    def __init__(self):
        self.seen = None
        holder = self

        def reader(*given):
            # As ctypes hands a C function its pointers: the addresses.
            mesh, map_id, corners, counts, face_count, edges, edge_weights, edge_room, points, point_weights, point_room, made = (
                v.value if isinstance(v, ctypes.c_void_p) else v for v in given)
            flat = (ctypes.c_uint32 * edge_room).from_address(corners)
            sizes = (ctypes.c_int32 * face_count).from_address(counts)
            holder.seen = (mesh, map_id, list(flat), list(sizes))
            pairs = (ctypes.c_int32 * (2 * edge_room)).from_address(edges)
            weights = (ctypes.c_float * edge_room).from_address(edge_weights)
            pairs[0], pairs[1], weights[0] = 0, 1, .25
            pairs[2], pairs[3], weights[1] = 1, 2, 1.5
            (ctypes.c_int32 * point_room).from_address(points)[0] = 3
            (ctypes.c_float * point_room).from_address(point_weights)[0] = .5
            done = (ctypes.c_longlong * 2).from_address(made)
            done[0], done[1] = 2, 1
            return None
        self.MR_subdivision_creases = reader


class CreasesNatively(unittest.TestCase):
    def test_faces_as_lists_and_weights_as_sharpness(self):
        adapter = Adapter()
        creases, corners = wrapper(adapter)(Mesh(), 99, [[0, 1, 2, 3], [1, 2, 4]])
        self.assertEqual(adapter.seen, (1234, 99, [0, 1, 2, 3, 1, 2, 4], [4, 3]))
        self.assertEqual(creases, [(0, 1, 2.5), (1, 2, 10.0)])
        self.assertEqual(corners, [(3, 5.0)])

    def test_faces_from_the_mesh_reader_go_as_they_came(self):
        adapter = Adapter()
        faces = rows.Faces(array('i', [0, 1, 2, 3, 1, 2, 4]), array('i', [4, 3]), 'x')
        wrapper(adapter)(Mesh(), 7, faces)
        self.assertEqual(adapter.seen[2:], ([0, 1, 2, 3, 1, 2, 4], [4, 3]))

    def test_no_reader_reads_in_python(self):
        self.assertIsNone(wrapper(types.SimpleNamespace())(Mesh(), 7, [[0, 1, 2]]))
        self.assertIsNone(wrapper(None)(Mesh(), 7, [[0, 1, 2]]))

    def test_the_python_reading_is_kept_behind_it(self):
        source = (KIT / 'moonray_modo/host.py').read_text(encoding='utf-8')
        start = source.index('def subdivision_creases(')
        body = source[start:source.index('\ndef ', start + 1)]
        self.assertIn('creases_natively(mesh, map_id, faces)', body)
        self.assertIn('edge.SelectEndpoints', body)


if __name__ == '__main__':
    unittest.main()
