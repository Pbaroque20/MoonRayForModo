"""Realtime previews' geometry (moonlightipr_detail, simplify.py, rdla): a dense mesh made lighter by the geometry
adapter with its UVs and materials kept, the dicing camera held while the view moves little, and a realtime scene's
subdivided mesh tessellated by MoonRay to the pixels the cut says, from that held camera."""
import math
import os
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_detail as detail, rdla, simplify  # noqa: E402

# The adapter as built here (tools/build_modo_bridge.py), else the kit's.
for built in sorted((ROOT / 'build').glob('modo-bridge*/MoonRayGeometry.lx'), key=lambda p: p.stat().st_mtime, reverse=True):
    os.environ.setdefault('MOONRAY_MODO_GEOMETRY', str(built))
    break


def sphere(rings=60, segments=120, name='ball', material=None):
    """A UV sphere of radius 1 as a polygon mesh: quads, face-varying UVs, and two materials, top and bottom."""
    vertices = [[0.0, 1.0, 0.0]]
    for r in range(1, rings):
        theta = math.pi * r / rings
        for s in range(segments):
            phi = 2 * math.pi * s / segments
            vertices.append([math.sin(theta) * math.cos(phi), math.cos(theta), math.sin(theta) * math.sin(phi)])
    vertices.append([0.0, -1.0, 0.0])
    faces, uvs, tags = [], [], []
    ring = lambda r, s: 1 + (r - 1) * segments + s % segments
    for r in range(1, rings - 1):
        for s in range(segments):
            faces.append([ring(r, s), ring(r, s + 1), ring(r + 1, s + 1), ring(r + 1, s)])
            uvs += [[s / segments, r / rings], [(s + 1) / segments, r / rings], [(s + 1) / segments, (r + 1) / rings], [s / segments, (r + 1) / rings]]
            tags.append('top' if r < rings // 2 else 'bottom')
    return {'name': name, 'identity': name, 'vertices': vertices, 'faces': faces, 'uvs': uvs, 'face_materials': tags, 'smooth': True,
            'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, -10, 1]}


@unittest.skipUnless(simplify.library() is not None, 'the geometry adapter with MR_simplify')
class Simplify(unittest.TestCase):
    def test_a_dense_mesh_made_lighter_keeps_its_lists_and_materials(self):
        mesh = sphere()
        triangles = sum(len(f) - 2 for f in mesh['faces'])
        lighter = simplify.polygon_mesh(mesh, triangles // 16, 0.01)
        self.assertIsNotNone(lighter)
        count = len(lighter['faces'])
        self.assertLess(count, triangles // 4)
        self.assertGreater(count, 0)
        self.assertEqual(len(lighter['uvs']), 3 * count)
        self.assertEqual(len(lighter['normals']), 3 * count)
        self.assertEqual(set(lighter['face_materials']), {'top', 'bottom'})
        # The surface stays where it was: every point still on the sphere.
        for point in lighter['vertices']:
            self.assertAlmostEqual(math.sqrt(sum(c * c for c in point)), 1.0, places=2)

    def test_moonlightipr_packs_a_dense_mesh_lighter(self):
        import struct
        from moonray_modo import moonlightipr_scene
        mesh = sphere()
        mesh.pop('face_materials')
        whole = moonlightipr_scene.mesh_payload(mesh, {'': 0}, {'': 0})
        light = moonlightipr_scene.mesh_payload(mesh, {'': 0}, {'': 0}, {'triangles': 1000, 'error': 0.01})
        triangles = lambda packed: struct.unpack_from('<2I', packed[2])[1]
        self.assertLess(triangles(light), triangles(whole) // 4)
        # Smooth with no normals of its own: given the full mesh's, as normals of its own.
        self.assertTrue(light[1] & moonlightipr_scene.MESH_HAS_NORMALS)

    def test_a_mesh_with_lists_of_its_own_is_left(self):
        self.assertIsNone(simplify.polygon_mesh(dict(sphere(), point_attributes={'w': {'kind': 'float', 'values': []}}), 100, 0.01))


class HeldDicing(unittest.TestCase):
    CAMERA = {'projection': 'persp', 'focal_mm': 50.0, 'film_mm': 36.0, 'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}

    def setUp(self):
        detail._DICING['camera'] = None

    def test_held_while_the_view_moves_little(self):
        meshes = [sphere()]
        first = detail.held_dicing(self.CAMERA, meshes)
        nudged = dict(self.CAMERA, matrix=self.CAMERA['matrix'][:12] + [0.3, 0, 0, 1])
        self.assertIs(detail.held_dicing(nudged, meshes), first)
        far = dict(self.CAMERA, matrix=self.CAMERA['matrix'][:12] + [3.0, 0, 0, 1])
        self.assertIsNot(detail.held_dicing(far, meshes), first)
        zoomed = dict(far, focal_mm=80.0)
        self.assertEqual(detail.held_dicing(zoomed, meshes)['focal_mm'], 80.0)

    def test_kept_through_a_move_of_the_camera_and_looked_at_again_at_rest(self):
        # MoonRay's realtime: held whatever the view while the camera moves (each cut anew was a reload of the scene),
        # and cut anew at rest only where the view came far enough.
        meshes = [sphere()]
        at = lambda x, z: dict(self.CAMERA, matrix=self.CAMERA['matrix'][:12] + [x, 0, z, 1])
        first = detail.held_dicing(at(0, 10.0), meshes)
        far = at(0, 20.0)
        self.assertIs(detail.held_dicing(far, meshes, keep=True), first)
        # Twice as far: the meshes are half the size on screen, cut anew.
        self.assertTrue(detail.rested(far, meshes))
        # Round the scene at the same distance, or nudged: as they were cut (going round cut every mesh anew each step).
        self.assertFalse(detail.rested(at(3.0, 9.54), meshes))
        self.assertFalse(detail.rested(at(0.3, 10.0), meshes))
        # MoonRay's realtime, whose tessellation goes by what is in view: a turn past its limit too.
        turned = dict(at(0, 10.0), matrix=[0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 0, 0, 10.0, 1])
        self.assertFalse(detail.rested(turned, meshes))
        self.assertTrue(detail.rested(turned, meshes, 60.0))

    def test_a_kept_scene_keeps_its_dicing_camera(self):
        mesh = dict(sphere(rings=8, segments=16), subdivision=True, subdivision_level=3)
        mesh.pop('face_materials')
        scene = {'camera': self.CAMERA, 'meshes': [mesh], 'materials': {}, '_geometry_detail': 'fine'}
        before = rdla.scene_text(scene)
        moved = dict(scene, camera=dict(self.CAMERA, matrix=self.CAMERA['matrix'][:12] + [3.0, 0, 0, 1]), _detail_keep=True)
        dicing = lambda text: text[text.index('/modo/dicing_camera'):].split('}')[0]
        self.assertEqual(dicing(rdla.scene_text(moved)), dicing(before))


class RealtimeScene(unittest.TestCase):
    def test_a_realtime_scene_tessellates_by_the_cut_from_a_held_camera(self):
        detail._DICING['camera'] = None
        mesh = dict(sphere(rings=8, segments=16), subdivision=True, subdivision_level=3)
        mesh.pop('face_materials')
        scene = {'camera': HeldDicing.CAMERA, 'meshes': [mesh], 'materials': {}}
        # A standard render follows Modo's Displacement Rate, from the render camera; Uniform has no screen error.
        still = rdla.scene_text(scene)
        self.assertIn('["adaptive_error"] = 1,', still)
        self.assertNotIn('["adaptive_error"]', rdla.scene_text(dict(scene, render_settings={'displacement_tessellation': 0})))
        self.assertNotIn('/modo/dicing_camera', still)
        text = rdla.scene_text(dict(scene, _geometry_detail='coarse'))
        self.assertIn('["adaptive_error"] = ', text)
        self.assertIn('/modo/dicing_camera', text)


if __name__ == '__main__':
    unittest.main()
