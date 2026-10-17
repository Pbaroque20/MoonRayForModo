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

    def test_a_copy_moves_only_as_moonray_moves_it(self):
        # The instancer does not use its prototype's own transform, so the prototype's motion moves no copy.
        data = rdl_import.plan(document(), 'moving.rdla')
        copies = [record for record in data['instances'] + data['meshes'] if 'many' in record['name'].lower() or record['name'] == 'repeated']
        self.assertEqual(len(copies), 2)
        self.assertFalse(any('matrix_close' in record for record in copies))

    def instanced(self, attributes, prototype_close=None):
        value = document()
        many = next(o for o in value['objects'] if o['name'] == '/geo/many')
        many['attributes'] = dict(attributes, references=['/geo/repeated'])
        if prototype_close is not None:
            next(o for o in value['objects'] if o['name'] == '/geo/repeated')['close'] = {'node_xform': prototype_close}
        data = rdl_import.plan(value, 'moving.rdla')
        return sorted((record['matrix'][12], (record.get('matrix_close') or [None] * 13)[12])
                      # The first copy is the mesh itself, under the prototype's name; the rest are instances of it.
                      for record in data['instances'] + data['meshes'] if 'many' in record['name'].lower() or record['name'] == 'repeated')

    def test_closing_transforms_move_the_copies(self):
        self.assertEqual(self.instanced({'method': 2, 'xform_list': [at(5), at(6)], 'xform_list_close': [at(7), at(9)]}),
                         [(5, 7), (6, 9)])

    def test_velocities_move_the_copies(self):
        # One unit a second over a shutter of -0.25 to 0.25 frames at 24 frames a second.
        moved = self.instanced({'method': 0, 'positions': [[0, 0, 0]], 'velocities': [[24, 0, 0]]})
        self.assertAlmostEqual(moved[0][0], -0.25)
        self.assertAlmostEqual(moved[0][1], 0.25)

    def test_a_prototype_moved_through_its_own_transform(self):
        moved = self.instanced({'method': 2, 'xform_list': [at(5)], 'use_reference_xforms': True}, prototype_close=at(1))
        self.assertEqual(moved, [(5, 6)])

    def shaped(self, kind, attributes):
        value = document()
        value['objects'].append({'name': '/geo/changing', 'type': kind, 'attributes': attributes})
        layer = next(o for o in value['objects'] if o['name'] == 'layer')['attributes']
        layer['geometries'] = layer['geometries'] + ['/geo/changing']
        layer['parts'] = layer['parts'] + ['']
        layer['surface_shaders'] = layer['surface_shaders'] + ['paint']
        return rdl_import.plan(value, 'moving.rdla')

    def test_a_mesh_that_changes_shape_carries_its_closing_points(self):
        data = self.shaped('RdlMeshGeometry', dict(TRIANGLE, vertex_list_1=[[0, 0, 0], [1, 0, 0], [0, 2, 0]]))
        changing = next(m for m in data['meshes'] if m['name'] == 'changing')
        self.assertEqual(changing['vertices_close'][2], [0, 2, 0])
        self.assertFalse(any('changes shape' in warning for warning in data['warnings']))

    def test_a_mesh_moved_by_its_velocities(self):
        data = self.shaped('RdlMeshGeometry', dict(TRIANGLE, velocity_list_0=[[0, 0, 0], [0, 0, 0], [0, 24, 0]]))
        changing = next(m for m in data['meshes'] if m['name'] == 'changing')
        self.assertAlmostEqual(changing['vertices'][2][1], 0.75)
        self.assertAlmostEqual(changing['vertices_close'][2][1], 1.25)

    def test_curves_that_change_shape_carry_their_closing_points(self):
        line = [[0, 0, 0], [0, 1, 0], [0, 2, 0], [0, 3, 0]]
        data = self.shaped('RdlCurveGeometry', {'curves_vertex_count': [4], 'vertex_list_0': line, 'curve_type': 0, 'radius_list': [0.01],
                                                'vertex_list_1': [[x + 1, y, z] for x, y, z in line]})
        changing = next(c for c in data['curves'] if c['name'].startswith('changing'))
        self.assertEqual(changing['lines_close'][0][3], [1, 3, 0])


if __name__ == '__main__':
    unittest.main()
