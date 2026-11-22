"""A mesh's UVs are written once for MoonRay and XPU2 where a layer lays its image on with the mesh's own UV map as it
is (coordinates.aliased_keys): its named set held the very numbers of the mesh's uv_list and of modo_primary_uv, a
third copy. The layer reads modo_primary_uv instead: the same numbers under another name. A tester's dragon carried
each mesh's UVs three times, 6 MB a copy of its 42 MB scene."""
import re
import sys
import unittest
from array import array
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import coordinates, rdla, rows  # noqa: E402

UVS = [[0, 0], [1, 0], [1, 1], [0, 1]]
TILED = [[0, 0], [2, 0], [2, 2], [0, 2]]


def quad(name, uvs, sets, material='skin'):
    return {'name': name, 'identity': name, 'vertices': [[-1, -1, -3], [1, -1, -3], [1, 1, -3], [-1, 1, -3]],
            'faces': [[0, 1, 2, 3]], 'face_materials': [material], 'uvs': uvs, 'uv_sets': sets}


def scene(meshes, layers):
    return {'camera': {'matrix': rdla.IDENTITY, 'focal_mm': 35, 'film_mm': 36},
            'materials': {'': {'color': [.5] * 3}, 'skin': {'color': [.7, .4, .2], 'shader': 'DwaBaseMaterial', 'layers': layers}},
            'meshes': meshes}


def image(key, effect='diffCol'):
    return {'kind': 'imageMap', 'effect': effect, 'path': 'fixture.png', 'tile_u': 'repeat', 'tile_v': 'repeat',
            'coordinate_key': key, 'image_channel': 'use'}


def written(value):
    with patch('moonray_modo.textures.prepare', return_value='fixture.tx'):
        return rdla.scene_text(value)


def user_data_keys(text):
    return re.findall(r'\["vec2f_key"\] = "([^"]+)"', text)


class AliasedKeys(unittest.TestCase):
    def test_a_set_that_is_the_meshs_own_uvs(self):
        meshes = [quad('a', UVS, {'own': [list(uv) for uv in UVS], 'same': UVS, 'tiled': TILED})]
        self.assertEqual(coordinates.aliased_keys(meshes), {'own', 'same'})

    def test_on_every_mesh_that_has_it(self):
        meshes = [quad('a', UVS, {'own': list(UVS)}), quad('b', UVS, {'own': TILED})]
        self.assertEqual(coordinates.aliased_keys(meshes), set())

    def test_the_very_same_numbers(self):
        held = rows.Rows(array('f', [0, 0, 1, 0, 1, 1, 0, 1]), 2, None)
        again = rows.Rows(array('f', [0, 0, 1, 0, 1, 1, 0, 1]), 2, None)
        self.assertEqual(coordinates.aliased_keys([quad('a', held, {'own': again})]), {'own'})
        # Numbers held otherwise (tuples) are written as they were.
        self.assertEqual(coordinates.aliased_keys([quad('a', UVS, {'own': [tuple(uv) for uv in UVS]})]), set())
        self.assertEqual(coordinates.aliased_keys([quad('a', [], {'own': UVS})]), set())


class Written(unittest.TestCase):
    def test_once_where_the_layer_lays_on_the_meshs_own_uvs(self):
        text = written(scene([quad('a', UVS, {'modo_uv_own': [list(uv) for uv in UVS]})], [image('modo_uv_own')]))
        self.assertEqual(user_data_keys(text), ['modo_primary_uv'])
        self.assertIn('["primitive_attribute_name"] = "modo_primary_uv"', text)
        self.assertNotIn('modo_uv_own', text)
        self.assertEqual(coordinates.aliased(), frozenset())

    def test_a_tiled_set_is_its_own(self):
        text = written(scene([quad('a', UVS, {'modo_uv_tiled': TILED})], [image('modo_uv_tiled')]))
        self.assertEqual(sorted(user_data_keys(text)), ['modo_primary_uv', 'modo_uv_tiled'])
        self.assertIn('["primitive_attribute_name"] = "modo_uv_tiled"', text)

    def test_a_normal_map_measures_from_the_same_attribute(self):
        text = written(scene([quad('a', UVS, {'modo_uv_own': list(UVS)})], [image('modo_uv_own', 'normal')]))
        self.assertEqual(user_data_keys(text), ['modo_primary_uv'])
        self.assertIn('["uv_name"] = "modo_primary_uv"', text)

    def test_kept_where_another_mesh_holds_other_numbers_under_its_key(self):
        text = written(scene([quad('a', UVS, {'modo_uv_own': list(UVS)}), quad('b', UVS, {'modo_uv_own': TILED})],
                             [image('modo_uv_own')]))
        self.assertEqual(sorted(user_data_keys(text)), ['modo_primary_uv', 'modo_primary_uv', 'modo_uv_own', 'modo_uv_own'])
        self.assertIn('["primitive_attribute_name"] = "modo_uv_own"', text)


if __name__ == '__main__':
    unittest.main()
