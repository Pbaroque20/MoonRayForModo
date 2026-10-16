"""Fog in Cryptomatte: a VDB carries its Cryptomatte IDs for MoonRay to read, and is in the manifest, only with the
preference on (MOONRAY_MODO_CRYPTO_VOLUMES, which MoonRay reads as it starts)."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import cryptomatte, native, rdla


def scene(categories=False):
    aovs = [{'name': 'Mask_' + c, 'kind': 'cryptomatte', 'category': c} for c in (('object', 'material', 'asset') if categories else ('object',))]
    return {'camera': {'matrix': rdla.IDENTITY, 'film_mm': 36, 'focal_mm': 50}, 'lights': [],
            'materials': {'a': {'name': 'Red', 'color': [1, 0, 0]}},
            'meshes': [{'identity': 'mesh1', 'name': 'Floor', 'material': 'a', 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                        'faces': [[0, 1, 2]], 'matrix': rdla.IDENTITY}],
            'extra_geometry': [{'kind': 'vdb', 'identity': 'cloud1|vdb', 'source_item': 'cloud1', 'name': 'Cloud',
                                'file': 'C:/clouds/cloud.vdb', 'matrix': rdla.IDENTITY}],
            '_crypto_categories': categories, 'custom_aovs': aovs}


def vdb_block(text):
    start = text.index('VdbGeometry(')
    return text[start:text.index('\n', start)]


class CryptoVolumes(unittest.TestCase):
    def render(self, on, categories=False):
        with mock.patch.dict(os.environ, {'MOONRAY_MODO_CRYPTO_VOLUMES': '1' if on else '0'}), \
                mock.patch.object(native, '_switch', lambda key, variable: os.environ.get(variable) == '1'):
            return rdla.scene_text(scene(categories), 16, 16, 1, 0, 'test.exr')

    def test_vdb_has_ids_and_a_matte_with_the_preference_on(self):
        text = self.render(True)
        self.assertIn('primitive_attributes', vdb_block(text))
        self.assertIn('Cloud [cloud1]', text)
        self.assertIn('%08x' % cryptomatte.hash32('Cloud [cloud1]'), text)

    def test_vdb_is_left_out_with_the_preference_off(self):
        text = self.render(False)
        self.assertNotIn('primitive_attributes', vdb_block(text))
        self.assertNotIn('Cloud [cloud1]', text)

    def test_all_three_categories_take_a_vdb(self):
        # Once refused: "Volume Cryptomatte coverage is not implemented".
        text = self.render(True, categories=True)
        block = vdb_block(text)
        self.assertIn('primitive_attributes', block)
        for key in ('modo_object_id', 'modo_material_id', 'modo_asset_id'):
            self.assertIn(key, text)

    def test_fog_without_a_material_is_its_own_material_matte(self):
        entry = scene()['extra_geometry'][0]
        self.assertEqual(cryptomatte.name(entry, 'material', scene()), 'Cloud [cloud1]')

    def test_a_moonray_box_of_fog_has_ids_and_a_matte(self):
        value = scene()
        value.pop('extra_geometry')
        value['entities'] = [{'identity': 'fogvol', 'name': 'Fog', 'class': 'BaseVolume', 'parameters': {}},
                             {'identity': 'box', 'name': 'Box', 'class': 'BoxGeometry', 'parameters': {'modo_volume': 'Fog', 'size': [1, 1, 1]}}]
        for on in (True, False):
            with mock.patch.dict(os.environ, {'MOONRAY_MODO_CRYPTO_VOLUMES': '1' if on else '0'}),                     mock.patch.object(native, '_switch', lambda key, variable: os.environ.get(variable) == '1'):
                lines = rdla.scene_text(value, 16, 16, 1, 0, 'test.exr').splitlines()
            start = lines.index('RdlMeshGeometry("/modo/entity/box") {')
            box = lines[start:lines.index('}', start)]
            self.assertEqual(any('primitive_attributes' in line for line in box), on)
            self.assertEqual('Box [box]' in next(line for line in lines if 'manifest' in line), on)

    def test_moonray_hears_the_preference(self):
        with mock.patch.object(native, 'crypto_volumes', lambda: True):
            self.assertEqual(native.environment('.')['MOONRAY_MODO_CRYPTO_VOLUMES'], '1')
        with mock.patch.object(native, 'crypto_volumes', lambda: False):
            self.assertEqual(native.environment('.')['MOONRAY_MODO_CRYPTO_VOLUMES'], '0')

    def test_moonray_hears_the_two_fixes(self):
        for on in (True, False):
            with mock.patch.object(native, 'fog_alpha', lambda: on), mock.patch.object(native, 'crypto_once', lambda: on):
                env = native.environment('.')
            self.assertEqual(env['MOONRAY_MODO_FOG_ALPHA'], '1' if on else '0')
            self.assertEqual(env['MOONRAY_MODO_CRYPTO_ONCE'], '1' if on else '0')


if __name__ == '__main__':
    unittest.main()
