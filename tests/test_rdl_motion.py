"""An imported MoonRay scene that blurs motion: what moves on its own carries its place at shutter close, to be keyed as
Modo animation, and the scene's shutter comes with it; what an instancer repeats still comes in as at shutter open."""
import sys
import types
import unittest
from pathlib import Path

for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import rdl_import

TRIANGLE = {'vertex_list_0': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'face_vertex_count': [3], 'vertices_by_index': [0, 1, 2], 'is_subd': False}


def at(x):
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, x, 0, 0, 1]


def document(steps=(-0.25, 0.25)):
    objects = [
        {'name': 'vars', 'type': 'SceneVariables', 'attributes': {'layer': 'layer', 'camera': '/camera', 'motion_steps': list(steps)}},
        {'name': 'layer', 'type': 'Layer', 'attributes': {'geometries': ['/geo/box', '/geo/repeated'], 'parts': ['', ''],
                                                          'surface_shaders': ['paint', 'paint']}},
        {'name': '/geo/box', 'type': 'RdlMeshGeometry', 'attributes': dict(TRIANGLE, node_xform=at(0)), 'close': {'node_xform': at(2)}},
        {'name': '/geo/repeated', 'type': 'RdlMeshGeometry', 'attributes': dict(TRIANGLE, node_xform=at(0)), 'close': {'node_xform': at(1)}},
        {'name': '/geo/many', 'type': 'RdlInstancerGeometry', 'attributes': {'references': ['/geo/repeated'], 'method': 2,
                                                                            'xform_list': [at(5), at(6)]}},
        {'name': 'paint', 'type': 'DwaBaseMaterial', 'attributes': {}},
        {'name': '/light/key', 'type': 'SphereLight', 'attributes': {'node_xform': at(0)}, 'close': {'node_xform': at(3)}},
        {'name': '/camera', 'type': 'PerspectiveCamera', 'attributes': {'node_xform': at(0), 'focal': 35}, 'close': {'node_xform': at(-1)}}]
    return {'version': 1, 'objects': objects}


class Motion(unittest.TestCase):
    def test_what_moves_on_its_own_carries_its_close(self):
        data = rdl_import.plan(document(), 'moving.rdla')
        # Placed once, the box is the mesh itself, keyed on import.
        box = next(record for record in data['meshes'] if record['name'] == 'box')
        self.assertEqual(box['matrix_close'][12], 2)
        light = next(record for record in data['entities'] if record['class'] == 'SphereLight')
        self.assertEqual(light['matrix_close'][12], 3)
        self.assertEqual(data['cameras'][0]['matrix_close'][12], -1)
        self.assertEqual(data['settings']['motion_steps'], [-0.25, 0.25])
        self.assertFalse(any('box' in warning and 'shutter' in warning for warning in data['warnings']))
        self.assertFalse(any('imported as it stands at shutter open' in warning for warning in data['warnings']))

    def test_without_motion_blur_nothing_is_keyed(self):
        data = rdl_import.plan(document(steps=(0.0,)), 'still.rdla')
        self.assertFalse(any('matrix_close' in record for record in data['meshes'] + data['instances'] + data['entities'] + data['cameras']))
        self.assertNotIn('motion_steps', data['settings'])

    def test_what_an_instancer_repeats_comes_in_at_shutter_open(self):
        data = rdl_import.plan(document(), 'moving.rdla')
        self.assertTrue(any('repeated' in warning and 'shutter open' in warning for warning in data['warnings']))
        self.assertFalse(any('matrix_close' in record for record in data['instances'] if 'many' in record['name'].lower()))


if __name__ == '__main__':
    unittest.main()
