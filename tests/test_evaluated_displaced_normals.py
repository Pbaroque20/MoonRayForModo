"""Surfaces: Modo evaluated geometry, for MoonRay and XPU2, takes meshes Modo has displaced (host.by_engine), and Modo's
render cache gives them the normals of the surface before it was displaced: a bumped sphere carried its round sphere's
normals, so its bumps were lit flat and showed only in its outline. A surface whose material's Displacement layers
Modo baked into it (layers.collect notes them, baked_effects) takes its normals from the displaced points instead,
smooth across them, the points Modo split along its seams joined (rows.joined_normals, evaluated.meshes)."""
import math
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADAPTER = ROOT / 'build/modo-bridge/MoonRayGeometry.lx'
os.environ.setdefault('MOONRAY_MODO_GEOMETRY', str(ADAPTER))
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import rows  # noqa: E402

SOURCE = ROOT / 'kit/MoonRayForModo/python/moonray_modo'


def bumpy(size, split):
    """A sheet of quads with bumps, its points split down the middle column where split (as Modo splits a displaced
    surface's points along its seams): the same places, two numbers."""
    height = lambda x, z: 0.3 * math.sin(x * 1.3) * math.cos(z * 0.9)
    vertices = [[float(x), height(x, z), float(z)] for z in range(size + 1) for x in range(size + 1)]
    at = lambda x, z: z * (size + 1) + x
    twins = {}
    if split:
        middle = size // 2
        for z in range(size + 1):
            twins[at(middle, z)] = len(vertices)
            vertices.append(list(vertices[at(middle, z)]))
    faces = []
    for z in range(size):
        for x in range(size):
            face = [at(x, z), at(x, z + 1), at(x + 1, z + 1), at(x + 1, z)]
            if split and x >= size // 2:
                face = [twins.get(i, i) for i in face]
            faces.append(face)
    return vertices, faces


@unittest.skipUnless(ADAPTER.is_file(), 'the geometry adapter is not built (tools/build_modo_bridge.py)')
class JoinedNormals(unittest.TestCase):
    def setUp(self):
        if rows._native() is None or rows._smoothing(rows._native()) is None:
            self.skipTest('the adapter has no MR_smooth_normals')

    def test_points_split_along_a_seam_are_smoothed_as_one(self):
        whole = rows.joined_normals(*bumpy(8, False))
        split = rows.joined_normals(*bumpy(8, True))
        self.assertEqual(len(whole), len(split))
        for a, b in zip(whole, split):
            for x, y in zip(a, b):
                self.assertAlmostEqual(x, y, places=5)

    def test_split_without_joining_creases_the_seam(self):
        # What the adapter's smoothing alone makes of the split sheet: the two sides of the seam apart.
        vertices, faces = bumpy(8, True)
        apart, _ = rows.smooth_normals(vertices, faces, None, -1.0)
        joined = rows.joined_normals(vertices, faces)
        self.assertGreater(max(max(abs(x - y) for x, y in zip(a, b)) for a, b in zip(apart, joined)), 1e-3)

    def test_the_normals_follow_the_bumps(self):
        vertices, faces = bumpy(8, False)
        normals = rows.joined_normals(vertices, faces)
        # Not all straight up, as the flat sheet's were.
        self.assertLess(min(n[1] for n in normals), 0.99)


class Marked(unittest.TestCase):
    def test_a_baked_layer_is_noted_on_its_material(self):
        source = (SOURCE / 'layers.py').read_text(encoding='utf-8')
        self.assertIn("noted = materials[material_key].setdefault('baked_effects', [])", source)

    def test_displaced_surfaces_take_normals_from_their_points(self):
        source = (SOURCE / 'evaluated.py').read_text(encoding='utf-8')
        self.assertIn("if 'displace' in (material.get('baked_effects') or ()):", source)
        self.assertIn('joined_normals(vertices, segment[\'faces\'])', source)


if __name__ == '__main__':
    unittest.main()
