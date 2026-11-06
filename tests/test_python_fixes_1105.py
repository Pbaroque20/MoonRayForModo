"""The Python-only fixes of the native audit (2026-11-05): work that grew with faces, instances or strands at every
write or edit, now done once while its lists stay the same ones."""
import sys
import unittest
from array import array
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo/python'
sys.path.insert(0, str(KIT))
from moonray_modo import cryptomatte, rdla, rdlb, scene_digest  # noqa: E402


class FacePartsKept(unittest.TestCase):
    def test_the_same_parts_while_the_list_is_the_same(self):
        tags = ['a', 'b', 'a', 'gone']
        materials = {'a': {}, 'b': {}, '': {}}
        first = rdla._parts_of(tags, materials)
        self.assertEqual(first, {'a': [0, 2], 'b': [1], '': [3]})
        self.assertIs(rdla._parts_of(tags, materials), first)
        self.assertIsNot(rdla._parts_of(list(tags), materials), first)


class CryptomatteByMaterial(unittest.TestCase):
    def scene(self):
        return {'materials': {'red': {'name': 'Red'}, 'blue': {'name': 'Blue'}},
                'custom_aovs': [{'kind': 'cryptomatte', 'category': 'material'}]}

    def test_ids_made_once_from_the_materials(self):
        tags = ['red', 'blue', 'red']
        mesh = {'face_materials': tags, 'material': 'red'}
        made = cryptomatte.ids(mesh, 'material', self.scene())
        self.assertIsInstance(made, array)
        expected = [cryptomatte.as_float(held) for _, held, _ in cryptomatte.entries(mesh, 'material', self.scene())]
        self.assertEqual(list(made), list(array('f', expected)))
        self.assertIs(cryptomatte.ids(mesh, 'material', self.scene()), made)

    def test_written_as_a_heavy_list_and_the_manifest_from_the_materials(self):
        mesh = {'face_materials': ['red', 'blue', 'red'], 'material': 'red'}
        lines = []
        with rdlb.collecting() as sink:
            cryptomatte.userdata(mesh, lines, 'material', self.scene())
        self.assertTrue(any('-- rdlb ["float_values_0"]' in line for line in lines))
        self.assertEqual(len(sink.objects), 1)
        self.assertEqual(cryptomatte.mattes([mesh], 'material', self.scene()),
                         {label: held for label, held, _ in cryptomatte.entries(mesh, 'material', self.scene())})


class BinaryObjectsOnce(unittest.TestCase):
    def test_an_attribute_written_once(self):
        thing = rdlb.SceneObject('UserData', '/modo/crypto/x')
        thing.add(rdlb.FLOAT_VECTOR, 'float_values_0', b'1')
        thing.add(rdlb.FLOAT_VECTOR, 'float_values_0', b'1')
        self.assertEqual(len(thing.parts), 1)


class DigestByList(unittest.TestCase):
    def test_instances_and_maps_hashed_by_the_list(self):
        values = [[0.0, 1.0, 2.0]] * 1000
        mesh = {'vertices': [[0, 0, 0]], 'instances': [[1, 0, 0, 0] * 4] * 500,
                'point_attributes': {'rest': {'kind': 'vec3', 'values': values}}}
        first = scene_digest.digest({'meshes': [mesh]})
        self.assertEqual(scene_digest.digest({'meshes': [dict(mesh)]}), first)
        moved = dict(mesh, instances=[[2, 0, 0, 0] * 4] * 500)
        self.assertNotEqual(scene_digest.digest({'meshes': [moved]}), first)
        self.assertIn('instances', scene_digest.HEAVY)


class CurvesInTheBinaryFile(unittest.TestCase):
    def test_strands_points_and_uvs_go_to_the_binary_file(self):
        from moonray_modo import extra_geometry
        entry = {'kind': 'curves', 'identity': 'hair', 'name': 'Hair', 'vertices': [[0, 0, 0], [0, 1, 0]] * 3,
                 'counts': [2, 2, 2], 'radii': [.01] * 6, 'uvs': [[0, 0], [0, 1]] * 3, 'material': ''}
        lines = []
        with rdlb.collecting():
            extra_geometry.emit({'extra_geometry': [entry]}, {'': {}}, lines)
        text = '\n'.join(lines)
        for attribute in ('vertex_list_0', 'radius_list', 'uv_list'):
            self.assertIn('-- rdlb ["%s"]' % attribute, text)
        self.assertIn('["curves_vertex_count"] = {2, 2, 2},', text)


if __name__ == '__main__':
    unittest.main()
