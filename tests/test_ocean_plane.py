"""The Ocean Plane (ocean_plane, entity_catalog OceanPlaneGeometry): an item of the kit's own made a mesh at each
reading, rings around the camera out to the horizon with UVs fixed to the world, wearing a sea made from its own
settings (the Ocean node's), or its tag's material; left out where the Ocean nodes override is off."""
import os
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
for _name in ('lx', 'lxu', 'lxifc', 'modo'):
    sys.modules.setdefault(_name, types.ModuleType(_name))
from moonray_modo import entities, ocean_plane  # noqa: E402

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def plane(**own):
    return {'class': 'OceanPlaneGeometry', 'name': 'Ocean Plane', 'identity': 'plane1', 'parameters': dict(own),
            'matrix': IDENTITY[:13] + [1.5, 0, 1]}


def scene(*items, materials=None):
    return {'camera': {'matrix': IDENTITY[:12] + [30.0, 4.0, 900.0, 1], 'focal_mm': 35.0, 'film_mm': 36.0},
            'materials': dict(materials or {}), 'meshes': [], 'entities': list(items), 'lights': [], 'environments': [], 'time': 0.0}


class OceanPlane(unittest.TestCase):
    def test_the_item_is_in_the_catalog_with_the_ocean_nodes_settings(self):
        held = entities.catalog()['OceanPlaneGeometry']
        self.assertEqual(held['override'], 'ocean')
        self.assertEqual(entities.display('OceanPlaneGeometry'), 'Ocean Plane')
        for key in ('wind_speed', 'wave_height', 'choppiness', 'foam_threshold', 'horizon', 'detail', 'tile_size', 'modo_material'):
            self.assertIn(key, held['attributes'])
        self.assertNotIn('fit_to_mesh', held['attributes'])

    def test_rings_around_the_camera_to_the_horizon_facing_up(self):
        item = plane(horizon=5000.0, detail=2.0)
        vertices, faces, uvs = ocean_plane.made(item, scene()['camera']['matrix'], lambda k: entities.value(item, k))
        centre = vertices[0]
        # Under the camera (to the nearest 16 x Detail), at height 0: the item's height is the mesh's matrix (lift).
        self.assertEqual(centre[1], 0.0)
        self.assertAlmostEqual(centre[0], 32.0)
        self.assertAlmostEqual(centre[2], 896.0)
        far = max(((v[0] - centre[0]) ** 2 + (v[2] - centre[2]) ** 2) ** .5 for v in vertices)
        self.assertAlmostEqual(far, 5000.0, places=3)
        self.assertEqual(len(uvs), sum(len(f) for f in faces))
        for face in faces[:3] + faces[-3:]:
            a, b, c = (vertices[i] for i in face[:3])
            e1 = [b[j] - a[j] for j in range(3)]
            e2 = [c[j] - a[j] for j in range(3)]
            self.assertGreater(e1[2] * e2[0] - e1[0] * e2[2], 0.0)   # up
        # The UVs are the world's, a tile (80 m) a unit: the waves stay put as the rings follow the camera.
        self.assertAlmostEqual(uvs[0][0], vertices[faces[0][0]][0] / 80.0)

    def test_quads_alone_for_moonrays_even_tessellation(self):
        # The centre too, two wedges a quad: MoonRay's even tessellation (realtime's sea) broke a triangle among quads
        # into walls and shards (the user's dragon, 2026-11-23). Every point of the first ring still in the centre's quads.
        item = plane(horizon=5000.0, detail=2.0)
        vertices, faces, uvs = ocean_plane.made(item, scene()['camera']['matrix'], lambda k: entities.value(item, k))
        self.assertEqual({len(f) for f in faces}, {4})
        centre = [f for f in faces if f[0] == 0]
        self.assertEqual(len(centre), ocean_plane.SEGMENTS // 2)
        self.assertEqual({i for f in centre for i in f[1:]}, set(range(1, ocean_plane.SEGMENTS + 1)))
        from moonray_modo import rdla
        self.assertTrue(rdla.quads_alone(faces))
        self.assertFalse(rdla.quads_alone(faces + [[0, 1, 2]]))

    def test_realtime_dices_a_sea_evenly_only_where_it_is_quads(self):
        text = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/rdla.py').read_text(encoding='utf-8')
        self.assertIn("<= OCEAN_TRIANGLES and (subdivision or quads_alone(faces)):", text)

    def test_it_becomes_a_mesh_wearing_its_own_sea(self):
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}):
            result = ocean_plane.apply(scene(plane(wind_speed=14.0)), [])
        self.assertEqual(result['entities'], [])
        mesh, = result['meshes']
        self.assertTrue(mesh['_ocean_plane'])
        sea = result['materials'][mesh['material']]['node_graph']['nodes']['sea']
        self.assertEqual(sea['parameters']['wind_speed'], 14.0)
        self.assertFalse(sea['parameters']['fit_to_mesh'])
        self.assertEqual(result['materials'][mesh['material']]['node_graph']['displacement'], 'waves')

    def test_a_tag_with_a_material_is_worn_instead(self):
        own = {'native_shader': 'DwaBaseMaterial', 'native_parameters': {}, 'color': [1, 0, 0]}
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}):
            result = ocean_plane.apply(scene(plane(modo_material='Sea'), materials={'Sea': own}), [])
        self.assertEqual(result['meshes'][0]['material'], 'Sea')

    def test_left_out_without_the_ocean_override(self):
        warnings = []
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '0'}):
            result = ocean_plane.apply(scene(plane()), warnings)
        self.assertEqual(result['meshes'], [])
        self.assertEqual(result['entities'], [])
        self.assertTrue(any('Ocean nodes' in w for w in warnings))

    def test_moonray_displaces_it_and_moonlightipr_displaces_it_itself(self):
        from moonray_modo import rdla, moonlightipr_scene, ocean
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(ocean, 'folder', return_value=pathlib.Path(folder)), \
                mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}):
            result = ocean_plane.apply(scene(plane(resolution=64, horizon=400.0, detail=4.0)), [])
            text = rdla.scene_text(result, 64, 36, 1, 0.2)
            self.assertIn('VectorDisplacement(', text)
            payload, keys, warnings = moonlightipr_scene.pack(result, 64, 36, 0.15, (), 4, False, None)
            key = next(iter(keys))
            at = bytes(payload).find(bytes(key))
            import struct
            self.assertTrue(struct.unpack_from("<I", payload, at + len(key))[0] & moonlightipr_scene.MESH_DISPLACE)



class OceanPlaneHeight(unittest.TestCase):
    """An Ocean Plane moved up or down (ocean_plane.lift): its points at height 0 and its item's height its mesh's matrix,
    so that a move followed in the preview moves it as any item's. It was drawn twice as high (2.5 m at 5 m) beside the
    plane kept from before, and motion blur refused the scene for its two meshes of one name."""

    LEVEL = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0]

    def test_its_height_is_its_matrix_and_its_rings_stay_under_the_camera(self):
        turned = plane()
        # The item turned and moved aside as well: the sea stays level, its rings under the camera.
        turned['matrix'] = [0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 40.0, 2.5, -7.0, 1]
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}):
            mesh, = ocean_plane.apply(scene(turned), [])['meshes']
        self.assertEqual(mesh['matrix'], self.LEVEL + [0, 2.5, 0, 1])
        self.assertTrue(all(v[1] == 0.0 for v in mesh['vertices']))
        self.assertAlmostEqual(mesh['vertices'][0][0], 32.0)

    def test_a_kept_plane_is_made_again_one_mesh_of_its_name(self):
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}):
            first = ocean_plane.apply(scene(plane()), [])
            # A followed edit's reading keeps the meshes of the last one (host.snapshot reuse_geometry).
            again = scene(plane())
            again['meshes'] = [dict(mesh) for mesh in first['meshes']]
            result = ocean_plane.apply(again, [])
        self.assertEqual([mesh['identity'] for mesh in result['meshes']], ['plane1'])

    def test_a_move_followed_or_at_the_shutters_ends_lifts_it_by_its_items_height_alone(self):
        from types import SimpleNamespace
        from moonray_modo import incremental
        mesh = {'identity': 'plane1', 'matrix': ocean_plane.lift(plane()['matrix']), 'vertices': [[0, 0, 0]], '_ocean_plane': True}
        snapshot = {'meshes': [mesh], 'extra_geometry': []}
        there = [0, 0, -1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 40.0, -1.0, -7.0, 1]
        host = types.ModuleType('moonray_modo.host')
        host.world_matrix = lambda held: list(there)
        found = SimpleNamespace(item=lambda identity: SimpleNamespace(id=identity))
        with mock.patch.dict(sys.modules, {'moonray_modo.host': host}), \
                mock.patch.object(incremental, 'transform_targets', return_value=None):
            incremental.refresh_transforms(found, snapshot, None)
        self.assertEqual(mesh['matrix'], self.LEVEL + [0, -1.0, 0, 1])
        mesh['matrix'] = ocean_plane.lift(plane()['matrix'])
        with mock.patch.dict(sys.modules, {'moonray_modo.host': host}):
            incremental.follow_items(found, snapshot, {'plane1': plane()['matrix']})
        self.assertEqual(mesh['matrix'], self.LEVEL + [0, -1.0, 0, 1])


class DistanceSplit(unittest.TestCase):
    """MoonLightIPR splits a displaced mesh by its distance from the camera (moonlightipr_scene.distance_split): the
    camera in the mesh's own space, snapped so small moves keep the cut, and the angle an edge may span."""

    def mesh(self, **own):
        return dict({'vertices': [[-400, 0, -400], [400, 0, -400], [400, 0, 400], [-400, 0, 400]], 'faces': [[0, 1, 2, 3]],
                     'matrix': IDENTITY[:12] + [10.0, 0.0, 0.0, 1]}, **own)

    def test_the_camera_in_the_meshs_space_and_the_angle_of_two_pixels(self):
        from moonray_modo import moonlightipr_scene
        camera = {'matrix': IDENTITY[:12] + [13.0, 3.0, 0.0, 1], 'focal_mm': 36.0, 'film_mm': 36.0}
        place, angle = moonlightipr_scene.distance_split(self.mesh(), camera, 1000)
        self.assertAlmostEqual(place[0], 3.0, delta=1.0)
        self.assertAlmostEqual(place[1], 3.0, delta=1.0)
        self.assertAlmostEqual(angle, 2.0 / 1000)
        # A small move keeps the same cut; a larger one does not.
        moved = moonlightipr_scene.distance_split(self.mesh(), dict(camera, matrix=IDENTITY[:12] + [13.05, 3.0, 0.0, 1]), 1000)
        self.assertEqual(moved[0], place)

    def test_instanced_meshes_and_no_camera_split_evenly(self):
        from moonray_modo import moonlightipr_scene
        camera = {'matrix': IDENTITY, 'focal_mm': 36.0, 'film_mm': 36.0}
        self.assertIsNone(moonlightipr_scene.distance_split(self.mesh(instances=[IDENTITY, IDENTITY]), camera, 1000))
        self.assertIsNone(moonlightipr_scene.distance_split(self.mesh(), None, 1000))


class DraftSplit(unittest.TestCase):
    """In Draft (_draft) a sea is split from the camera its meshes are cut from, held through its edits: split from the
    camera itself, each step of a camera drag gave the sea a new key and the session displaced it again. A realtime
    preview's sea is split from the camera held since it came on (moonlightipr_detail.held_sea). Any other mesh, and a
    render's sea, is split from the camera itself as before."""

    def split_from(self, detail=True, **flags):
        from moonray_modo import moonlightipr_scene, moonlightipr_detail, ocean
        held = {'matrix': IDENTITY[:12] + [0.0, 4.0, 0.0, 1], 'focal_mm': 35.0, 'film_mm': 36.0}
        sea_held = {'matrix': IDENTITY[:12] + [0.0, 6.0, 0.0, 1], 'focal_mm': 35.0, 'film_mm': 36.0}
        seen = {}
        real = moonlightipr_scene.displaced

        def displaced(mesh, *args):
            seen[mesh['name']] = args[7]    # the camera: after key, flags, payload, materials, index, warnings, limit
            return real(mesh, *args)
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(ocean, 'folder', return_value=pathlib.Path(folder)), \
                mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), \
                mock.patch.object(moonlightipr_detail, 'held_dicing', lambda *a, **k: held), \
                mock.patch.object(moonlightipr_detail, 'held_sea', lambda *a, **k: sea_held), \
                mock.patch.object(moonlightipr_scene, 'displaced', displaced):
            result = ocean_plane.apply(scene(plane(resolution=64, horizon=400.0, detail=4.0)), [])
            sea = result['meshes'][0]
            floor = dict(DistanceSplit().mesh(), name='Floor', material='floor')
            result = dict(result, meshes=[sea, floor], materials=dict(result['materials'], floor={}), **flags)
            if detail:
                result = dict(result, _geometry_detail='coarse', _detail_keep=True)
            moonlightipr_scene.pack(result, 64, 36, 0.15, (), 4, False, None)
        return seen[sea['name']], seen['Floor'], held, sea_held, result['camera']

    def test_a_drafts_sea_from_the_held_camera_and_the_rest_from_the_camera(self):
        sea, floor, held, _, camera = self.split_from(_draft=2)
        self.assertIs(sea, held)
        self.assertIs(floor, camera)

    def test_a_realtime_sea_from_the_camera_held_since_realtime_came_on(self):
        sea, floor, _, sea_held, camera = self.split_from()
        self.assertIs(sea, sea_held)
        self.assertIs(floor, camera)

    def test_a_renders_sea_from_the_camera(self):
        sea, floor, _, _, camera = self.split_from(detail=False)
        self.assertIs(sea, camera)
        self.assertIs(floor, camera)


class RealtimeSeaOnce(unittest.TestCase):
    """A realtime preview displaces a sea once (moonlightipr_detail.held_sea): its key stays the same through moves of the
    view, until realtime comes on again (forget_sea). An Ocean Plane, whose rings stand under the camera, takes it again
    where its rings moved."""

    def sea_key(self, place, meshes=None):
        from moonray_modo import moonlightipr_scene, ocean
        keys = {}
        real = moonlightipr_scene.displaced

        def displaced(mesh, key, *args):
            made = real(mesh, key, *args)
            if made[0] != key:
                keys[mesh['name']] = made[0]
            return made
        with tempfile.TemporaryDirectory() as folder, mock.patch.object(ocean, 'folder', return_value=pathlib.Path(folder)), \
                mock.patch.dict(os.environ, {'MOONRAY_MODO_OCEAN': '1'}), \
                mock.patch.object(moonlightipr_scene, 'displaced', displaced):
            held = scene(plane(resolution=64, horizon=400.0, detail=4.0))
            held['camera'] = dict(held['camera'], matrix=IDENTITY[:12] + [place, 4.0, 30.0, 1])
            result = ocean_plane.apply(held, [])
            if meshes is not None:
                # A mesh of the scene's own wearing the plane's sea.
                sea = dict(DistanceSplit().mesh(), name='Sea', material=result['meshes'][0]['material'])
                result = dict(result, meshes=[sea])
            moonlightipr_scene.pack(dict(result, _geometry_detail='fine', _detail_keep=True), 64, 36, 0.15, (), 4, False, None)
        return keys

    def setUp(self):
        from moonray_modo import moonlightipr_detail
        moonlightipr_detail.forget_sea()
        self.addCleanup(moonlightipr_detail.forget_sea)

    def test_a_sea_keeps_its_key_through_moves_of_the_view(self):
        from moonray_modo import moonlightipr_detail
        first = self.sea_key(13.0, meshes=True)
        self.assertEqual(list(first), ['Sea'])
        self.assertEqual(self.sea_key(40.0, meshes=True), first)
        self.assertEqual(self.sea_key(90.0, meshes=True), first)
        moonlightipr_detail.forget_sea()
        self.assertNotEqual(self.sea_key(90.0, meshes=True), first)

    def test_an_ocean_planes_camera_taken_again_where_its_rings_moved(self):
        first = self.sea_key(30.0)
        self.assertEqual(len(first), 1)
        # Within a step of its rings (ocean_plane.SNAP, 16 x Detail = 64): the same.
        self.assertEqual(self.sea_key(31.0), first)
        # Its rings moved: a new mesh, cut from where the camera now stands.
        self.assertNotEqual(self.sea_key(200.0), first)


if __name__ == '__main__':
    unittest.main()
