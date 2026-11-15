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
        # Under the camera (to the nearest 16 x Detail), at the item's height.
        self.assertEqual(centre[1], 1.5)
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


if __name__ == '__main__':
    unittest.main()
