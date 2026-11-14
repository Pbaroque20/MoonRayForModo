"""Evaluated geometry Modo gave no UVs: its faces take the mesh's own UVs, exactly where they are the mesh's polygons,
by the triangle they lie on where Modo split them (evaluated_uvs.borrowed)."""
import sys
import pathlib
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import evaluated_uvs  # noqa: E402


def held():
    """A 2 x 1 plane of two quads, a UV seam between them (the second quad's UVs start again at 0)."""
    points = [(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 0.0, 1.0), (1.0, 0.0, 1.0), (2.0, 0.0, 1.0)]
    indices = [0, 1, 4, 3, 1, 2, 5, 4]
    uvs = [0, 0, 1, 0, 1, 1, 0, 1, 0, 0, 1, 0, 1, 1, 0, 1]
    owners = [[] for _ in points]
    for polygon, start in enumerate((0, 4)):
        for i in indices[start:start + 4]:
            owners[i].append(polygon)
    return {'points': points, 'names': ['Texture'], 'counts': [4, 4], 'starts': [0, 4, 8], 'indices': indices,
            'uvs': [[float(v) for v in uvs]], 'place': {p: i for i, p in enumerate(points)}, 'owners': owners}


class Borrowed(unittest.TestCase):
    def test_exact_triangles_keep_the_seam(self):
        # Modo's triangles of the mesh's own points: the corner at x = 1 has u 1 in the first quad, 0 in the second.
        segment = {'vertices': [[0, 0, 0], [1, 0, 0], [1, 0, 1], [2, 0, 0], [2, 0, 1]],
                   'faces': [[0, 1, 2], [1, 3, 4]], 'face_varying': True}
        values = evaluated_uvs.borrowed(segment, held(), [])[0]
        self.assertEqual(values[1], [1.0, 0.0])
        self.assertEqual(values[3], [0.0, 0.0])
        self.assertEqual(values[4], [1.0, 0.0])

    def test_split_faces_found_on_the_mesh(self):
        # A point inside the first quad, as subdividing makes: its UV where it stands.
        segment = {'vertices': [[0.25, 0, 0.5], [0.5, 0, 0.5], [0.5, 0, 0.75]], 'faces': [[0, 1, 2]], 'face_varying': True}
        values = evaluated_uvs.borrowed(segment, held(), [])[0]
        for (u, v), (x, z) in zip(values, ((0.25, 0.5), (0.5, 0.5), (0.5, 0.75))):
            self.assertAlmostEqual(u, x, 5)
            self.assertAlmostEqual(v, z, 5)

    def test_wanted(self):
        self.assertTrue(evaluated_uvs.wanted({'node_graph': {'nodes': {'n': {'type': 'ocean'}}}}))
        self.assertFalse(evaluated_uvs.wanted({'node_graph': {'nodes': {'n': {'type': 'constant'}}}}))


if __name__ == '__main__':
    unittest.main()
