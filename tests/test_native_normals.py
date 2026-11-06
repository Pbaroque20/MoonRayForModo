"""Smoothed normals by the geometry adapter (native-modo/smooth_normals.cpp, rows.smooth_normals) against
geometry.prepare's own Python: the same normal at every corner, by material and by object smoothing angle. A car's 6
million corners took a minute of Python on one core; the adapter does it on all of them (2026-11-05)."""
import math
import os
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / 'build/modo-bridge/MoonRayGeometry.lx'
os.environ.setdefault('MOONRAY_MODO_GEOMETRY', str(ADAPTER))
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import geometry, rows  # noqa: E402


def grid(size, wobble, seed):
    """A bumpy sheet of quads, with a fan of triangles and an n-gon closing one side, and a fold down the middle."""
    chance = random.Random(seed)
    vertices = [[x, (abs(x - size / 2) * 0.8 if wobble else 0.0) + chance.uniform(-wobble, wobble), z]
                for z in range(size + 1) for x in range(size + 1)]
    at = lambda x, z: z * (size + 1) + x
    faces = [[at(x, z), at(x, z + 1), at(x + 1, z + 1), at(x + 1, z)] for z in range(size) for x in range(size)]
    # Split some quads into triangles, and add an n-gon off one edge.
    split = []
    for face in faces:
        if chance.random() < 0.3:
            split += [[face[0], face[1], face[2]], [face[0], face[2], face[3]]]
        else:
            split.append(face)
    base = len(vertices)
    vertices += [[-1.0, 0.5, z * size / 5.0] for z in range(6)]
    split.append([at(0, 0)] + [base + k for k in range(6)][::-1][:5] + [at(0, size)][:0] + [base + 5])
    return vertices, split


def by_python(mesh):
    held = rows.smooth_normals
    rows.smooth_normals = lambda *a, **k: None
    try:
        return geometry.prepare(mesh)
    finally:
        rows.smooth_normals = held


def close(a, b):
    return all(abs(x - y) < 2e-5 for p, q in zip(a, b) for x, y in zip(p, q)) and len(a) == len(b)


@unittest.skipUnless(ADAPTER.is_file(), 'the geometry adapter is not built (tools/build_modo_bridge.py)')
class NativeNormals(unittest.TestCase):
    def setUp(self):
        geometry._SMOOTHED.clear()
        if rows._native() is None or rows._smoothing(rows._native()) is None:
            self.skipTest('the adapter has no MR_smooth_normals')

    def test_by_material(self):
        vertices, faces = grid(12, 0.3, 1)
        tags = [('a', 'b', 'c')[i % 3] for i in range(len(faces))]
        mesh = {'vertices': vertices, 'faces': faces, 'face_materials': tags,
                'material_smoothing': {'a': 20.0, 'b': 60.0}}
        expected = by_python(dict(mesh))['normals']
        geometry._SMOOTHED.clear()
        made = geometry.prepare(dict(mesh))['normals']
        self.assertIsInstance(made, rows.Rows)
        self.assertTrue(close([list(n) for n in made], expected))

    def test_by_object_angle(self):
        vertices, faces = grid(10, 0.5, 2)
        for angle in (5.0, 40.0, 89.0):
            mesh = {'vertices': vertices, 'faces': faces, 'material': '',
                    'geometry_settings': {'override': True, 'normal_override': True, 'smooth': True, 'smoothing_angle': angle}}
            expected = by_python(dict(mesh))['normals']
            made = geometry.prepare(dict(mesh))['normals']
            with self.subTest(angle=angle):
                self.assertTrue(close([list(n) for n in made], expected))

    def test_flat_runs_as_modo_hands_them(self):
        # Points and faces as the adapter hands them over (rows.Rows, rows.Faces): taken as they are.
        from array import array
        vertices, faces = grid(6, 0.2, 3)
        points = rows.Rows(array('f', [v for p in vertices for v in p]), 3, 'p')
        flat = rows.Faces(array('i', [i for f in faces for i in f]), array('i', [len(f) for f in faces]), 'f')
        made, bend = rows.smooth_normals(points, flat, None, math.cos(math.radians(30)))
        listed, again = rows.smooth_normals(vertices, faces, None, math.cos(math.radians(30)))
        self.assertEqual(list(made.data), list(listed.data))
        self.assertAlmostEqual(bend, again)


if __name__ == '__main__':
    unittest.main()


class RowsInTheDigest(unittest.TestCase):
    """'Render unavailable: unmarshallable object' (2026-11-05): a scene read without Modo's render cache left the
    digest's hook for rows unset, and marshal could not write the Rows it met."""

    def test_rows_hashed_without_the_hook(self):
        from array import array
        from moonray_modo import scene_digest
        held = list(scene_digest.FLAT)
        scene_digest.FLAT[:] = []
        scene_digest._remembered.clear()
        try:
            points = rows.Rows(array('f', [0.0, 1.0, 2.0]), 3, 'points:abc')
            faces = rows.Faces(array('i', [0, 0, 0]), array('i', [3]), 'faces:abc')
            self.assertEqual(scene_digest.content(points), 'points:abc')
            self.assertEqual(scene_digest.content(faces), 'faces:abc')
            scene_digest.digest({'meshes': [{'vertices': points, 'faces': faces, 'normals': points}]})
        finally:
            scene_digest.FLAT[:] = held
