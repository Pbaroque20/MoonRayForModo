"""The Backplate item (backplate.py): its projections, the camera's card, its ground, and the environments it gives."""
import math
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import backplate, entities  # noqa: E402

# A 50 mm camera 1.5 m up at z = 10, looking down -Z.
CAMERA = {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1.5, 10, 1], 'focal_mm': 50.0, 'film_mm': 36.0,
          'film_offset': [0.0, 0.0], 'pixel_aspect': 1.0, 'projection': 'persp'}


class Projections(unittest.TestCase):
    def test_front_puts_the_view_centre_in_the_middle(self):
        p = backplate.Projector('front', CAMERA, 16 / 9.0)
        u, v = p.point([0, 1.5, 0])
        self.assertAlmostEqual(u, 0.5)
        self.assertAlmostEqual(v, 0.5)

    def test_front_edges_are_the_frames(self):
        p = backplate.Projector('front', CAMERA, 16 / 9.0)
        # At 10 m, half the film (18 mm) over 50 mm: 3.6 m to the right edge.
        u, v = p.point([3.6, 1.5, 0])
        self.assertAlmostEqual(u, 1.0)
        self.assertIsNone(p.point([3.7, 1.5, 0]))
        self.assertIsNotNone(p.point([3.7, 1.5, 0], clip=False))
        self.assertIsNone(p.point([0, 1.5, 20]))           # behind the camera

    def test_the_card_fills_the_frame(self):
        vertices, faces, uvs = backplate.card(CAMERA, 16 / 9.0, 100.0)
        p = backplate.Projector('front', CAMERA, 16 / 9.0)
        for vertex, uv in zip(vertices, uvs):
            got = p.point(vertex)
            self.assertAlmostEqual(got[0], uv[0], places=6)
            self.assertAlmostEqual(got[1], uv[1], places=6)

    def test_planar_lays_the_photo_on_the_ground(self):
        p = backplate.Projector('planar', place=backplate.IDENTITY, size=10.0)
        self.assertEqual(p.point([0, 0, 0]), (0.5, 0.5))
        self.assertEqual(p.point([5, 0, -5]), (1.0, 1.0))

    def test_spherical_and_the_latlong_agree(self):
        p = backplate.Projector('spherical', place=backplate.IDENTITY, size=2.0)
        width, height = 64, 32
        for x, y in ((0, 5), (17, 16), (40, 30), (63, 1)):
            u, v = p.direction(backplate.latlong_direction(x, y, width, height))
            self.assertAlmostEqual(u % 1.0, (x + .5) / width, places=6)
            self.assertAlmostEqual(v, 1 - (y + .5) / height, places=6)

    def test_box_takes_the_side_it_lies_toward(self):
        p = backplate.Projector('box', place=backplate.IDENTITY, size=2.0)
        self.assertEqual(p.point([0.2, 1.0, 0.0]), (0.6, 0.5))       # the top
        u, v = p.point([1.0, 0.1, 0.0])                                # the +X side
        self.assertAlmostEqual(v, 0.55)

    def test_inverse(self):
        m = [0, 0, -2, 0, 0, 2, 0, 0, 2, 0, 0, 0, 1, 2, 3, 1]
        point = [0.3, -1.0, 4.0]
        back = backplate.transform(backplate.inverse(m), backplate.transform(m, point))
        for a, b in zip(back, point):
            self.assertAlmostEqual(a, b)


class Ground(unittest.TestCase):
    def test_a_grid_facing_up(self):
        vertices, faces = backplate.ground({}, 4.0, cells=2)
        self.assertEqual(len(vertices), 9)
        self.assertEqual(len(faces), 4)
        a, b, c = (vertices[i] for i in faces[0][:3])
        # (b - a) x (c - a) points up.
        e, f = [q - p for p, q in zip(a, b)], [q - p for p, q in zip(a, c)]
        self.assertGreater(e[2] * f[0] - e[0] * f[2], 0)

    def test_corners_keep_a_face_whole_across_the_seam(self):
        p = backplate.Projector('cylindrical', place=backplate.IDENTITY, size=2.0)
        uvs = backplate.corner_uvs(p, [[-0.1, 0, 1], [0.1, 0, 1], [0.1, 0.5, 1]], [[0, 1, 2]], backplate.IDENTITY)
        us = [uv[0] for uv in uvs]
        self.assertLess(max(us) - min(us), 0.5)


class Environments(unittest.TestCase):
    def entity(self, **values):
        parameters = dict(values)
        return {'class': backplate.CLASS, 'identity': 'bp', 'name': 'Backplate', 'matrix': backplate.IDENTITY, 'parameters': parameters}

    def run_apply(self, scene, entity):
        scene = dict(scene, entities=[entity], camera=CAMERA, width=1920, height=1080)
        with mock.patch('moonray_modo.native.backplate', return_value=True), \
                mock.patch('moonray_modo.native.shadow_catcher_runtime', return_value=self.catching), \
                mock.patch.object(backplate, 'reflection_environment', side_effect=lambda *a, **k: pathlib.Path(self.made)):
            return backplate.apply(scene, [])

    catching = True

    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        base = pathlib.Path(self.folder.name)
        self.plate, self.hdri = base / 'plate.jpg', base / 'sky.exr'
        self.made = base / 'made.exr'
        for path in (self.plate, self.hdri, self.made):
            path.write_bytes(b'x')

    def tearDown(self):
        self.folder.cleanup()

    def test_replace_keeps_only_the_backdrop(self):
        modo = [{'name': 'gradient', 'camera': True, 'indirect': True, 'reflection': True, 'refraction': True},
                {'name': 'Camera background override', 'backdrop': True, 'camera': True, 'indirect': False, 'reflection': False, 'refraction': False}]
        result = self.run_apply({'environments': modo}, self.entity(plate=str(self.plate), hdri=str(self.hdri)))
        names = [e['name'] for e in result['environments']]
        self.assertNotIn('gradient', names)
        self.assertIn('Backplate HDRI', names)
        self.assertIn('Backplate backplate', names)

    def test_the_hdri_lights_and_the_photo_reflects(self):
        result = self.run_apply({}, self.entity(plate=str(self.plate), hdri=str(self.hdri)))
        by = {e['name']: e for e in result['environments']}
        hdri, plate = by['Backplate HDRI'], by['Backplate backplate']
        self.assertTrue(hdri['indirect'])
        self.assertFalse(plate['indirect'])
        self.assertTrue(plate['reflection'])
        self.assertFalse(hdri['reflection'])
        self.assertFalse(hdri['camera'])

    def test_override_and_add(self):
        modo = [{'name': 'gradient', 'camera': True, 'indirect': True, 'reflection': True, 'refraction': True}]
        over = self.run_apply({'environments': [dict(m) for m in modo]}, self.entity(hdri=str(self.hdri), other_environments=1))
        gradient = next(e for e in over['environments'] if e['name'] == 'gradient')
        self.assertFalse(gradient['indirect'])          # the HDRI lights the scene; the gradient is under it
        self.assertTrue(gradient['camera'])              # the HDRI is not seen by the camera: the gradient is
        added = self.run_apply({'environments': [dict(m) for m in modo]}, self.entity(hdri=str(self.hdri), other_environments=2))
        gradient = next(e for e in added['environments'] if e['name'] == 'gradient')
        self.assertTrue(gradient['indirect'])

    def test_the_card_and_the_ground_are_made(self):
        result = self.run_apply({}, self.entity(plate=str(self.plate)))
        names = {m['name']: m for m in result['meshes']}
        self.assertIn('Backplate card', names)
        self.assertEqual(names['Backplate card']['visibility'][:2], [True, False])
        ground = names['Backplate ground']
        self.assertEqual(len(ground['uvs']), sum(len(f) for f in ground['faces']))
        material = result['materials'][ground['material']]
        self.assertEqual(material['shadow_catcher'], {'strength': 1.0, 'matte': False})
        # The photo its colour, and its emission, which the catcher shows.
        self.assertEqual(material['node_graph']['nodes']['surface']['inputs']['emission'], 'plate')
        self.assertNotIn(backplate.CLASS, [e['class'] for e in result['entities']])

    def test_without_a_catcher_in_the_runtime_the_ground_is_lit(self):
        self.catching = False
        result = self.run_apply({}, self.entity(plate=str(self.plate)))
        ground = next(m for m in result['meshes'] if m['name'] == 'Backplate ground')
        material = result['materials'][ground['material']]
        self.assertNotIn('shadow_catcher', material)
        self.assertNotIn('emission', material['node_graph']['nodes']['surface']['inputs'])

    def test_shadows_alone_for_compositing(self):
        result = self.run_apply({}, self.entity(plate=str(self.plate), catcher_shows_plate=False))
        names = {m['name']: m for m in result['meshes']}
        # The backdrop stays for refractions alone; the camera no longer sees it.
        self.assertEqual(names['Backplate card']['visibility'][:4], [False, False, False, True])
        self.assertTrue(result['materials'][names['Backplate ground']['material']]['shadow_catcher']['matte'])
        result = self.run_apply({}, self.entity(plate=str(self.plate), catcher_shows_plate=False, backdrop_refraction=False))
        self.assertNotIn('Backplate card', [m['name'] for m in result['meshes']])

    def test_a_backdrop_plane_at_its_distance(self):
        result = self.run_apply({}, self.entity(plate=str(self.plate), backdrop_distance=25.0))
        card = next(m for m in result['meshes'] if m['name'] == 'Backplate card')
        self.assertAlmostEqual(card['vertices'][0][2], 10 - 25.0)

    def test_off_without_its_source_override(self):
        scene = {'entities': [self.entity(plate=str(self.plate))], 'camera': CAMERA, 'width': 1920, 'height': 1080}
        warnings = []
        with mock.patch('moonray_modo.native.backplate', return_value=False):
            result = backplate.apply(scene, warnings)
        self.assertFalse(result.get('meshes'))
        self.assertTrue(any('Source Overrides' in w for w in warnings))


class MarkedCatchers(unittest.TestCase):
    """Objects made shadow catchers on their MoonRay Object tab (options.OBJECT shadow_catcher)."""

    def mesh(self, name, catcher=True, strength=0.5):
        return {'name': name, 'identity': name, 'vertices': [[0, 0, 0], [1, 0, 0], [1, 0, 1]], 'faces': [[0, 1, 2]],
                'material': 'paint', 'geometry_settings': {'shadow_catcher': catcher, 'shadow_strength': strength}}

    def test_without_a_backplate_a_matte(self):
        scene = {'meshes': [self.mesh('floor'), self.mesh('car', catcher=False)], 'materials': {'paint': {}}}
        with mock.patch('moonray_modo.native.shadow_catcher_runtime', return_value=True):
            backplate.catchers(scene, [])
        floor, car = scene['meshes']
        self.assertEqual(car['material'], 'paint')
        self.assertEqual(scene['materials'][floor['material']]['shadow_catcher'], {'strength': 0.5, 'matte': True})

    def test_plain_where_moonray_has_none(self):
        scene = {'meshes': [self.mesh('floor')], 'materials': {'paint': {}}}
        warnings = []
        with mock.patch('moonray_modo.native.shadow_catcher_runtime', return_value=False):
            backplate.catchers(scene, warnings)
        self.assertEqual(scene['meshes'][0]['material'], 'paint')
        self.assertTrue(warnings)

    def test_the_scene_says_so_to_moonray(self):
        from moonray_modo import rdla
        source = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/rdla.py').read_text(encoding='utf-8')
        self.assertIn('["modo_shadow_catcher"] = true', source)
        self.assertIn('shadow_catcher_runtime()', source)


class Catalog(unittest.TestCase):
    def test_a_kit_class_behind_its_override(self):
        entry = entities.catalog()[backplate.CLASS]
        self.assertEqual((entry['source'], entry['override']), ('kit', 'backplate'))
        self.assertEqual(entities.display(backplate.CLASS), 'Backplate')
        self.assertEqual(entry['attributes']['projection']['enum'], dict(zip(backplate.PROJECTIONS, range(6))))
        self.assertEqual(list(entry['attributes']['other_environments']['enum']), list(backplate.OTHERS))
        with mock.patch('moonray_modo.native.backplate', return_value=False):
            self.assertIn('Source Overrides', entities.override_off(backplate.CLASS))
        with mock.patch('moonray_modo.native.backplate', return_value=True):
            self.assertIsNone(entities.override_off(backplate.CLASS))

    def test_front_projection_from_the_render_camera(self):
        from moonray_modo import coordinates
        coordinates.FRONT.update(camera=CAMERA, aspect=16 / 9.0)
        layer = {'projection': 'front', 'locator_matrix': backplate.IDENTITY}
        uvs = coordinates.mesh_corners(layer, [[0, 1.5, 0], [3.6, 1.5, 0], [3.6, 3.525, 0]], [[0, 1, 2]], None,
                                       backplate.IDENTITY)
        got = [list(map(float, uv)) for uv in uvs]
        self.assertAlmostEqual(got[0][0], 0.5, places=5)
        self.assertAlmostEqual(got[1][0], 1.0, places=5)
        self.assertAlmostEqual(got[2][1], 1.0, places=5)
        self.assertNotEqual(coordinates.key(layer), coordinates.key(dict(layer, projection='planar')))


if __name__ == '__main__':
    unittest.main()
