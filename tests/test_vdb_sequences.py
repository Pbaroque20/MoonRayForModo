"""VDB sequences and blackbody fire (entities.vdb_pattern, vdb_sequence, vdb_frame_file, resolve_vdb), asked 2026-11-08."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
from moonray_modo import entities  # noqa: E402


class Sequences(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def files(self, names):
        for name in names:
            (self.root / name).write_bytes(b'')

    def test_unpadded_numbers_as_embergen_writes_them(self):
        self.files('fire_%d.vdb' % n for n in (0, 1, 2, 10, 40))
        pattern = entities.vdb_pattern(self.root / 'fire_40.vdb')
        self.assertEqual(Path(pattern).name, 'fire_#.vdb')
        self.assertEqual(entities.vdb_sequence(pattern), [0, 1, 2, 10, 40])

    def test_padded_numbers(self):
        self.files('smoke.%04d.vdb' % n for n in (1, 2, 3))
        self.assertEqual(Path(entities.vdb_pattern(self.root / 'smoke.0002.vdb')).name, 'smoke.####.vdb')

    def test_a_file_alone_stays_itself(self):
        self.files(['cloud_7.vdb', 'other_8.vdb'])
        self.assertEqual(Path(entities.vdb_pattern(self.root / 'cloud_7.vdb')).name, 'cloud_7.vdb')

    def test_outside_the_frames_hidden_or_held_and_gaps_hold_the_frame_before(self):
        self.files('fire_%d.vdb' % n for n in (5, 6, 8))
        pattern = str(self.root / 'fire_#.vdb')
        self.assertEqual(Path(entities.vdb_frame_file(pattern, 6, False)).name, 'fire_6.vdb')
        self.assertIsNone(entities.vdb_frame_file(pattern, 2, False))
        self.assertIsNone(entities.vdb_frame_file(pattern, 9, False))
        self.assertEqual(Path(entities.vdb_frame_file(pattern, 2, True)).name, 'fire_5.vdb')
        self.assertEqual(Path(entities.vdb_frame_file(pattern, 9, True)).name, 'fire_8.vdb')
        self.assertEqual(Path(entities.vdb_frame_file(pattern, 7, False)).name, 'fire_6.vdb')

    def test_the_frame_offset_and_a_hidden_volume(self):
        self.files('fire_%d.vdb' % n for n in (10, 11))
        pattern = str(self.root / 'fire_#.vdb')
        resolved = entities.resolve_vdb({'model': pattern, 'modo_frame_offset': 10}, {'frame': 1})
        self.assertEqual(Path(resolved['model']).name, 'fire_11.vdb')
        self.assertIsNone(entities.resolve_vdb({'model': pattern}, {'frame': 1}))

    def test_static_or_sequence_from_the_file_chosen(self):
        self.files('fire_%d.vdb' % n for n in (1, 2, 3))
        chosen = str(self.root / 'fire_2.vdb')
        self.assertEqual(Path(entities.resolve_vdb({'model': chosen}, {'frame': 3})['model']).name, 'fire_2.vdb')
        self.assertEqual(Path(entities.resolve_vdb({'model': chosen, 'modo_vdb_file': 1}, {'frame': 3})['model']).name, 'fire_3.vdb')
        self.assertIsNone(entities.resolve_vdb({'model': chosen, 'modo_vdb_file': 1}, {'frame': 9}))

    def test_blackbody_follows_its_switch(self):
        self.files(['hot_1.vdb'])
        given = {'model': str(self.root / 'hot_1.vdb'), 'emission_grid': 'temperature', 'modo_blackbody': True, 'modo_blackbody_kelvin': 2500.0}
        made = str(self.root / 'made.vdb')
        with mock.patch.object(entities, 'vdb_blackbody', return_value=made) as convert:
            with mock.patch.dict(sys.modules, {'PySide2': None}), mock.patch.dict(os.environ, {'MOONRAY_MODO_VDB_BLACKBODY': '1'}):
                resolved = entities.resolve_vdb(given, {'frame': 1})
            self.assertEqual((resolved['model'], resolved['emission_grid']), (made, 'modo_blackbody'))
            convert.assert_called_once_with(given['model'], 'temperature', 2500.0)
            with mock.patch.dict(sys.modules, {'PySide2': None}), mock.patch.dict(os.environ, {'MOONRAY_MODO_VDB_BLACKBODY': '0'}):
                resolved = entities.resolve_vdb(given, {'frame': 1})
            self.assertEqual((resolved['model'], resolved['emission_grid']), (given['model'], 'temperature'))

    def test_the_settings_and_the_switch_are_in_the_kit(self):
        attributes = entities.catalog()['VdbGeometry']['attributes']
        self.assertEqual(attributes['modo_vdb_file']['enum'], {'static': 0, 'sequence': 1})
        for key in ('modo_blackbody', 'modo_blackbody_kelvin', 'modo_frame_offset', 'modo_sequence_hold'):
            self.assertIn(key, attributes)
        page = (KIT / 'preferences.cfg').read_text(encoding='utf-8')
        self.assertIn('cmd moonray.pref.vdbBlackbody ?', page)
        self.assertIn("lx.bless(switch('vdb_blackbody'),'moonray.pref.vdbBlackbody')", (KIT / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8'))
        forms = (KIT / 'entities.cfg').read_text(encoding='utf-8')
        self.assertLess(forms.index('Label">model<'), forms.index('Label">file<'))


if __name__ == '__main__':
    unittest.main()
