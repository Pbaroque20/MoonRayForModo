"""An imported MoonRay scene's light, shadow and shadow receiver sets, planned as each mesh's Light Links; and MoonRay
light items named in the Light Links of a scene written out."""
import sys
import types
import unittest
from pathlib import Path

for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import rdl_import

TRIANGLE = {'vertex_list_0': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'face_vertex_count': [3], 'vertices_by_index': [0, 1, 2], 'is_subd': False}


def scene(layer):
    return {'version': 1, 'objects': [
        {'name': 'vars', 'type': 'SceneVariables', 'attributes': {'layer': 'layer'}},
        {'name': 'layer', 'type': 'Layer', 'attributes': dict({'geometries': ['/geo/wall', '/geo/floor'], 'parts': ['', ''], 'surface_shaders': ['paint', 'paint']}, **layer)},
        {'name': '/geo/wall', 'type': 'RdlMeshGeometry', 'attributes': dict(TRIANGLE)},
        {'name': '/geo/floor', 'type': 'RdlMeshGeometry', 'attributes': dict(TRIANGLE)},
        {'name': 'paint', 'type': 'DwaBaseMaterial', 'attributes': {}},
        {'name': '/light/key', 'type': 'SphereLight', 'attributes': {}},
        {'name': '/light/fill', 'type': 'RectLight', 'attributes': {}},
        {'name': 'both', 'type': 'LightSet', 'attributes': {'lights': ['/light/key', '/light/fill']}},
        {'name': 'keyOnly', 'type': 'LightSet', 'attributes': {'lights': ['/light/key']}},
        {'name': 'noFillShadow', 'type': 'ShadowSet', 'attributes': {'lights': ['/light/fill']}},
        {'name': 'notOnFloor', 'type': 'ShadowReceiverSet', 'attributes': {'geometries': ['/geo/floor']}}]}


class Sets(unittest.TestCase):
    def test_sets_become_the_links_of_the_meshes_they_are_on(self):
        data = rdl_import.plan(scene({'lightsets': ['keyOnly', 'both'], 'shadowsets': ['noFillShadow', None], 'shadowreceiversets': ['notOnFloor', None]}), 'test.rdla')
        names = {record['name'] for record in data['meshes']}
        lights = {record['name'] for record in data['entities']}
        self.assertEqual(len(data['links']), 1)
        link = data['links'][0]
        # The wall is lit by the key alone, casts no shadow for the fill, and none onto the floor.
        self.assertIn(link['geometry'], names)
        self.assertEqual(len(link['lights']), 1)
        self.assertEqual(len(link['shadows']), 1)
        self.assertNotEqual(link['lights'], link['shadows'])
        self.assertTrue(set(link['lights']) | set(link['shadows']) <= lights)
        self.assertEqual(len(link['receivers']), 1)
        self.assertIn(link['receivers'][0], names - {link['geometry']})
        self.assertFalse(any('not imported' in warning for warning in data['warnings']))

    def test_a_scene_lit_by_all_its_lights_has_no_links(self):
        self.assertEqual(rdl_import.plan(scene({'lightsets': ['both', 'both']}), 'test.rdla')['links'], [])
        self.assertEqual(rdl_import.plan(scene({}), 'test.rdla')['links'], [])


if __name__ == '__main__':
    unittest.main()
