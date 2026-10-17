"""A MoonRay mesh full of fog comes in as a mesh whose material holds the volume's item, and Modo's subdivision
weights go out to MoonRay as creases and corners."""
import sys
import types
import unittest
from pathlib import Path

for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import rdl_import, rdla

BOX = {'vertex_list_0': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'face_vertex_count': [3], 'vertices_by_index': [0, 1, 2], 'is_subd': False}


def document(surface):
    return {'version': 1, 'objects': [
        {'name': 'vars', 'type': 'SceneVariables', 'attributes': {'layer': 'layer'}},
        {'name': 'layer', 'type': 'Layer', 'attributes': {'geometries': ['/geo/fog'], 'parts': [''], 'surface_shaders': [surface],
                                                          'volume_shaders': ['/haze']}},
        {'name': '/geo/fog', 'type': 'RdlMeshGeometry', 'attributes': dict(BOX)},
        {'name': '/paint', 'type': 'DwaBaseMaterial', 'attributes': {}},
        {'name': '/haze', 'type': 'BaseVolume', 'attributes': {}}]}


class Volume(unittest.TestCase):
    def test_a_mesh_of_fog_alone(self):
        data = rdl_import.plan(document(''), 'fog.rdla')
        tags = data['meshes'][0]['tags']
        self.assertEqual(set(tags), {'volume:/haze'})
        self.assertEqual(data['materials']['volume:/haze'], {'name': 'haze fog', 'graph': None, 'volume': 'haze', 'volume_only': True})
        self.assertIn('BaseVolume', [record['class'] for record in data['entities']])
        self.assertFalse(any('volume' in warning for warning in data['warnings']))

    def test_a_surface_filled_with_fog(self):
        data = rdl_import.plan(document('/paint'), 'fog.rdla')
        tag = data['meshes'][0]['tags'][0]
        self.assertEqual(tag, '/paint|volume:/haze')
        self.assertEqual(data['materials'][tag]['volume'], 'haze')
        self.assertNotIn('volume_only', data['materials'][tag])

    def test_the_material_names_its_volume(self):
        self.assertEqual(rdla.material_volume({'moonray_volume': 'haze', 'volume_only': True}), ('haze', True))
        self.assertEqual(rdla.material_volume({'material_stack': [{'moonray_volume': 'a'}, {'moonray_volume': 'b'}]}), ('b', False))
        self.assertEqual(rdla.material_volume({}), ('', False))


class Creases(unittest.TestCase):
    def test_corners_go_to_moonray(self):
        mesh = {'identity': 'cube|True|', 'name': 'Cube', 'vertices': [[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]], 'faces': [[0, 1, 2, 3]],
                'material': '', 'matrix': rdla.IDENTITY, 'subdivision': True, 'creases': [(0, 1, 10.0)], 'corners': [(2, 3.0)]}
        text = rdla.scene_text({'camera': {'matrix': rdla.IDENTITY, 'film_mm': 36, 'focal_mm': 50}, 'lights': [], 'materials': {}, 'meshes': [mesh]}, 16, 16)
        self.assertIn('["subd_crease_sharpnesses"] = {10},', text)
        self.assertIn('["subd_corner_indices"] = {2},', text)
        self.assertIn('["subd_corner_sharpnesses"] = {3},', text)


if __name__ == '__main__':
    unittest.main()


class Vectors(unittest.TestCase):
    def test_a_vector_at_each_point_comes_in_as_a_colour_map_noted_as_a_vector(self):
        value = document('/paint')
        value['objects'][1]['attributes'].pop('volume_shaders')
        value['objects'][2]['attributes']['primitive_attributes'] = ['/data']
        value['objects'].append({'name': '/data', 'type': 'UserData', 'attributes': {
            'vec3f_key': 'rest', 'vec3f_values_0': [[1, 2, 3], [4, 5, 6], [7, 8, 9]], 'rate': 4}})
        data = rdl_import.plan(value, 'vectors.rdla')
        maps = data['meshes'][0]['maps']
        self.assertEqual([(name, word, rate) for name, word, rate, _ in maps], [('rest', 'vec3', 'points')])
        self.assertEqual(maps[0][3][1], [4, 5, 6])

    def test_a_colour_map_noted_as_a_vector_goes_out_as_one(self):
        # vertex_maps names Modo's map kinds as it loads; outside Modo they are given stand-ins.
        lx = sys.modules['lx']
        if not hasattr(lx, 'symbol'):
            lx.symbol = types.SimpleNamespace(i_VMAP_WEIGHT='WGHT', i_VMAP_RGB='RGB ', i_VMAP_RGBA='RGBA')
        lxu = sys.modules['lxu']
        if not hasattr(lxu, 'utils'):
            lxu.utils = types.ModuleType('lxu.utils')
            sys.modules['lxu.utils'] = lxu.utils
        lxu.__path__ = getattr(lxu, '__path__', [])
        from moonray_modo import vertex_maps
        maps = vertex_maps.as_vectors({'rest': {'kind': 'color', 'points': [[1, 2, 3], [4, 5, 6], [7, 8, 9]]}}, {'rest': 'vec2'})
        self.assertEqual(maps['rest'], {'kind': 'vec2', 'points': [[1, 2], [4, 5], [7, 8]]})
        mesh = {'identity': 'tri||', 'name': 'Tri', 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'faces': [[0, 1, 2]], 'material': '',
                'matrix': rdla.IDENTITY, 'point_attributes': {'rest': {'kind': 'vec3', 'values': [[1, 2, 3], [4, 5, 6], [7, 8, 9]]}}}
        text = rdla.scene_text({'camera': {'matrix': rdla.IDENTITY, 'film_mm': 36, 'focal_mm': 50}, 'lights': [], 'materials': {}, 'meshes': [mesh]}, 16, 16)
        self.assertIn('["vec3f_key"] = "rest",', text)
        self.assertIn('vec3f_values_0', text)
