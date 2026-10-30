"""n-gons as MoonRay triangulates them (polygons.py, TriMesh::splitNGons): a flat concave one ear-clipped so that its
triangles stay inside it, where a fan covered its notch; a quad, a face that is not flat and one with no area fanned;
and MoonLightIPR's packed mesh made of the ear-clipped triangles."""
import pathlib
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_scene, polygons  # noqa: E402

# An L of six corners, its notch at (1..2, 1..2), begun at a corner a fan from which crosses the notch.
L_SHAPE = [(2.0, 0.0, 0.0), (2.0, 1.0, 0.0), (1.0, 1.0, 0.0), (1.0, 2.0, 0.0), (0.0, 2.0, 0.0), (0.0, 0.0, 0.0)]


def inside_l(x, y):
    return 0 <= x <= 2 and 0 <= y <= 2 and not (x > 1 and y > 1)


def triangles(points, flat):
    return [tuple(points[flat[i + k]] for k in range(3)) for i in range(0, len(flat), 3)]


def area(t):
    (ax, ay, _), (bx, by, _), (cx, cy, _) = t
    return abs((bx - ax) * (cy - ay) - (cx - ax) * (by - ay)) / 2


class Polygons(unittest.TestCase):
    def test_a_concave_ngon_is_filled_where_it_is(self):
        clipped = polygons.ear_clip(L_SHAPE)
        self.assertIsNotNone(clipped)
        self.assertEqual(len(clipped), 3 * 4)
        tris = triangles(L_SHAPE, clipped)
        self.assertAlmostEqual(sum(map(area, tris)), 3.0)
        for t in tris:
            centre = (sum(p[0] for p in t) / 3, sum(p[1] for p in t) / 3)
            self.assertTrue(inside_l(*centre), t)
        # A fan from the first corner covers the notch.
        fanned = triangles(L_SHAPE, polygons.fan(6))
        self.assertGreater(sum(map(area, fanned)), 3.0)

    def test_what_moonray_fans(self):
        quad = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
        self.assertIsNone(polygons.ear_clip(quad))
        bent = [list(p) for p in L_SHAPE]
        bent[4][2] = 0.5
        self.assertIsNone(polygons.ear_clip(bent))
        self.assertIsNone(polygons.ear_clip([(0, 0, 0)] * 6))
        self.assertEqual(polygons.corners([0, 1, 2, 3], quad), polygons.fan(4))

    def test_a_small_outline_begun_at_its_notch(self):
        # As a CAD outline: a millimetre across, begun just before its inner corner (2), so that its first three corners turn
        # against it. MoonRay's own tests fan it, over its notch; the override's ear-clip it inside its outline.
        begun = L_SHAPE[1:] + L_SHAPE[:1]
        small = [(x * .001, y * .001, z) for x, y, z in begun]
        self.assertIsNone(polygons.ear_clip(small, clean=False))
        self.assertIsNone(polygons.ear_clip(begun, clean=False))
        for points, whole in ((small, 3e-6), (begun, 3.0)):
            clipped = polygons.ear_clip(points, clean=True)
            self.assertIsNotNone(clipped)
            tris = triangles(points, clipped)
            self.assertAlmostEqual(sum(map(area, tris)) / whole, 1.0)
            scale = 1000 if points is small else 1
            for t in tris:
                self.assertTrue(inside_l(sum(p[0] for p in t) / 3 * scale, sum(p[1] for p in t) / 3 * scale), t)

    def test_an_outline_with_a_hole_joined_by_a_seam(self):
        # As the tester's CAD faces: a 4 x 4 outline round a 2 x 2 hole, the two joined by a seam that the outline
        # passes twice, so two of its corners are each where another is. Its triangles cover the ring alone (16 - 4),
        # all facing as the face does; MoonRay's own tests find no ear past the seam and fan it over the hole.
        outer = [(0, 0, 0), (4, 0, 0), (4, 4, 0), (0, 4, 0)]
        hole = [(1, 1, 0), (1, 3, 0), (3, 3, 0), (3, 1, 0)]
        ring = [(0.0, 0.0, 0.0)] + [tuple(map(float, p)) for p in outer[1:]] + [(0.0, 0.0, 0.0)] + [tuple(map(float, p)) for p in hole] + [(1.0, 1.0, 0.0)]
        ring = [p for i, p in enumerate(ring) if i == 0 or p != ring[i - 1]]
        small = [(x * .001, y * .001, z) for x, y, z in ring]
        for points, scale in ((ring, 1.0), (small, .001)):
            clipped = polygons.ear_clip(points, clean=True)
            self.assertIsNotNone(clipped)
            tris = triangles(points, clipped)
            self.assertAlmostEqual(sum(map(area, tris)) / scale ** 2, 12.0, places=4)
            for t in tris:
                (ax, ay, _), (bx, by, _), (cx, cy, _) = t
                self.assertGreaterEqual((bx - ax) * (cy - ay) - (cx - ax) * (by - ay), -1e-12 * scale ** 2, t)
                centre = (sum(p[0] for p in t) / 3 / scale, sum(p[1] for p in t) / 3 / scale)
                self.assertFalse(1 < centre[0] < 3 and 1 < centre[1] < 3, t)

    def test_the_override_still_fans_what_is_not_flat(self):
        bent = [list(p) for p in L_SHAPE]
        bent[4][2] = 0.5
        self.assertIsNone(polygons.ear_clip(bent, clean=True))
        self.assertIsNone(polygons.ear_clip([(0, 0, 0)] * 6, clean=True))

    def test_the_rules_follow_the_switch(self):
        begun = L_SHAPE[1:] + L_SHAPE[:1]
        try:
            polygons.follow(False)
            self.assertEqual(polygons.rules(), 'moonray')
            self.assertEqual(polygons.corners(list(range(6)), begun), polygons.fan(6))
            polygons.follow(True)
            self.assertEqual(polygons.rules(), 'clean')
            self.assertNotEqual(polygons.corners(list(range(6)), begun), polygons.fan(6))
        finally:
            polygons.follow(True)

    def test_moonlightipr_packs_the_ear_clipped_triangles(self):
        mesh = {'name': 'L', 'vertices': [list(p) for p in L_SHAPE], 'faces': [[0, 1, 2, 3, 4, 5]], 'smooth': False}
        moonlightipr_scene._packed.clear()
        key, flags, payload, slots = moonlightipr_scene.mesh_payload(mesh, {'': 0}, {'': 0})
        points, count = struct.unpack_from('<2I', payload)
        self.assertEqual(count, 4)
        start = 8 + 4 * 3 * points
        indices = struct.unpack_from('<%dI' % (3 * count), payload, start)
        self.assertEqual(sorted(indices), sorted(polygons.ear_clip(L_SHAPE)))


class CutForMoonRay(unittest.TestCase):
    """MoonRay handed the n-gons cut as MoonLightIPR cuts them (polygons.cut_mesh, written by rdla), with the switch on."""

    def mesh(self, **more):
        # The L and a quad beside it: each corner's normal says which corner it was, and each face has a material.
        points = [list(p) for p in L_SHAPE] + [[3, 0, 0], [4, 0, 0], [4, 1, 0], [3, 1, 0]]
        faces = [[0, 1, 2, 3, 4, 5], [6, 7, 8, 9]]
        return dict({'name': 'L', 'vertices': points, 'faces': faces, 'normals': [[0, 0, float(i)] for i in range(10)],
                     'uvs': [[float(i), 0.0] for i in range(10)], 'face_materials': ['ell', 'quad'], 'smooth': True}, **more)

    def test_corners_and_faces_carried(self):
        cut = polygons.cut_mesh(self.mesh())
        self.assertEqual([len(f) for f in cut['faces']], [3, 3, 3, 3, 4])
        self.assertEqual(cut['face_materials'], ['ell'] * 4 + ['quad'])
        # Each new corner's normal and UV are those of the old corner its point was.
        old = self.mesh()
        corner_of = {}
        start = 0
        for face in old['faces']:
            for k, v in enumerate(face):
                corner_of.setdefault(v, start + k)
            start += len(face)
        flat = [v for face in cut['faces'] for v in face]
        self.assertEqual([n[2] for n in cut['normals']], [float(corner_of[v]) for v in flat])
        self.assertEqual([u[0] for u in cut['uvs']], [float(corner_of[v]) for v in flat])
        # A mesh with no n-gon is handed back as it is.
        quad = self.mesh(faces=[[6, 7, 8, 9]], normals=None, uvs=None, face_materials=['quad'])
        self.assertIs(polygons.cut_mesh(quad), quad)

    def scene_text(self, mesh, on):
        import os
        from unittest.mock import patch
        from moonray_modo import rdla
        scene = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 5, 1], 'focal_mm': 50.0, 'film_mm': 36.0},
                 'materials': {'': {'color': [.5, .5, .5]}, 'ell': {'color': [.5, .5, .5]}, 'quad': {'color': [.5, .5, .5]}},
                 'meshes': [mesh], 'lights': [], 'environments': []}
        with patch.dict(os.environ, {'MOONRAY_MODO_NGON_EARS': '1' if on else '0'}):
            return rdla.scene_text(scene, 64, 36, 1, 0.0)

    def test_moonray_is_handed_triangles_with_the_switch_on(self):
        on = self.scene_text(self.mesh(), True)
        self.assertIn('["face_vertex_count"] = {3, 3, 3, 3, 4}', on.replace('\n', ''))
        off = self.scene_text(self.mesh(), False)
        self.assertIn('["face_vertex_count"] = {6, 4}', off.replace('\n', ''))
        # A subdivision surface keeps its n-gons, which its limit surface needs.
        subd = self.scene_text(self.mesh(subdivision=True), True)
        self.assertIn('["face_vertex_count"] = {6, 4}', subd.replace('\n', ''))


class CutKept(unittest.TestCase):
    """A mesh cut again with the same lists, wherever it now stands, gives back the very lists cut before: the scene
    text keeps them written, and a move of a car with n-gons wrote every mesh's lists anew (6.7 s)."""
    HEX = [(0, 0, 0), (1, 0, 0), (1.5, 1, 0), (1, 2, 0), (0, 2, 0), (-.5, 1, 0)]

    def test_a_moved_mesh_gets_the_same_lists(self):
        mesh = {'vertices': self.HEX, 'faces': [[0, 1, 2, 3, 4, 5]], 'uvs': [(0, 0)] * 6, 'matrix': [1.0] * 16}
        first = polygons.cut_mesh(mesh)
        moved = polygons.cut_mesh(dict(mesh, matrix=[2.0] * 16))
        self.assertEqual(len(first['faces']), 4)
        self.assertIs(moved['faces'], first['faces'])
        self.assertIs(moved['uvs'], first['uvs'])
        self.assertEqual(moved['matrix'], [2.0] * 16)

    def test_new_lists_are_cut_again(self):
        mesh = {'vertices': self.HEX, 'faces': [[0, 1, 2, 3, 4, 5]]}
        first = polygons.cut_mesh(mesh)
        again = polygons.cut_mesh(dict(mesh, faces=[[0, 1, 2, 3, 4, 5]]))
        self.assertIsNot(again['faces'], first['faces'])
        self.assertEqual(again['faces'], first['faces'])


if __name__ == '__main__':
    unittest.main()
