"""Cryptomatte names and IDs given to objects and materials: a shared name is one matte, a number is the matte's ID,
and the manifest lists each ID as the bits of the float the matte is written with."""
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import cryptomatte


def mesh(name, item, material='paint', **extra):
    return dict({'name': name, 'item_id': item, 'identity': item, 'material': material}, **extra)


SCENE = {'materials': {'paint': {'name': 'Car Paint'}, 'glass': {'name': 'Glass', 'crypto_name': 'windows', 'crypto_id': 0},
                       'chrome': {'name': 'Chrome', 'crypto_id': 4242}},
         'cryptomatte_objects': {'door': {'name': 'car', 'id': 0}, 'hood': {'name': 'car', 'id': 0}, 'wheel': {'name': '', 'id': 77}}}


class Names(unittest.TestCase):
    def found(self, geometry, category='object'):
        return cryptomatte.entries(geometry, category, SCENE)

    def test_objects_given_one_name_share_a_matte(self):
        door, hood = self.found(mesh('Door', 'door')), self.found(mesh('Hood', 'hood'))
        self.assertEqual(door[0][:2], hood[0][:2])
        self.assertEqual(door[0][0], 'car')
        self.assertEqual(door[0][1], cryptomatte.bits(cryptomatte.hash32('car')))

    def test_an_object_given_no_name_keeps_its_own(self):
        label, held, key = self.found(mesh('Roof', 'roof'))[0]
        self.assertEqual(label, 'Roof [roof]')
        self.assertEqual(key, 'roof')

    def test_a_number_is_the_id(self):
        label, held, _ = self.found(mesh('Wheel', 'wheel'))[0]
        self.assertEqual(label, 'Wheel [wheel]')
        self.assertEqual(held, 77 ^ (1 << 23))     # 77 has no exponent: moved off, as any ID that would not be a number

    def test_materials_by_name_and_by_number(self):
        self.assertEqual(self.found(mesh('Pane', 'pane', 'glass'), 'material')[0][0], 'windows')
        chrome = self.found(mesh('Trim', 'trim', 'chrome'), 'material')[0]
        self.assertEqual(chrome[0], 'Chrome [chrome]')
        self.assertEqual(chrome[1], cryptomatte.bits(4242))
        self.assertEqual(self.found(mesh('Body', 'body', 'paint'), 'material')[0][0], 'Car Paint [paint]')

    def test_a_layered_material_is_called_what_its_top_layer_is(self):
        scene = {'materials': {'stack': {'material_stack': [{'name': 'Base'}, {'name': 'Top', 'crypto_name': 'rust'}]}}}
        self.assertEqual(cryptomatte.entries(mesh('Pipe', 'pipe', 'stack'), 'material', scene)[0][0], 'rust')

    def test_the_manifest_lists_the_ids_written(self):
        geometries = [mesh('Door', 'door'), mesh('Hood', 'hood'), mesh('Wheel', 'wheel')]
        found = cryptomatte.mattes(geometries, 'object', SCENE)
        self.assertEqual(set(found), {'car', 'Wheel [wheel]'})
        for label, held in found.items():
            written = struct.unpack('<I', struct.pack('<f', cryptomatte.as_float(held)))[0]
            self.assertEqual(written, held)
        self.assertEqual(cryptomatte.owners(geometries, 'object', SCENE)['car'], ['door', 'hood'])


if __name__ == '__main__':
    unittest.main()
