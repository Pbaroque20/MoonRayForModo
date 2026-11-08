"""Alembic meshes the kit reads itself (extra_geometry.alembic_scene_meshes) and their velocity motion blur, asked
2026-11-08 for a tester's fluid (Mesher.abc). Needs the built reader (build/native-avx/bin/modo_abc_reader.exe) and the
file in Downloads; skipped without them."""
import copy
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import extra_geometry, motion  # noqa: E402

READER = ROOT / 'build/native-avx/bin/modo_abc_reader.exe'
FLUID = Path(r'C:\Users\Raphael Tobar\Downloads\Mesher\Mesher.abc')
IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


@unittest.skipUnless(READER.is_file() and FLUID.is_file() and os.name == 'nt', 'needs the built Alembic reader and the tester file')
class AlembicMeshes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # A runtime folder of the reader alone, with the toolchain's Imath (the kit's runtime holds the same library).
        cls.folder = tempfile.TemporaryDirectory()
        cls.runtime = Path(cls.folder.name)
        shutil.copy2(READER, cls.runtime / READER.name)
        shutil.copy2(ROOT / 'toolchain/msys64/ucrt64/bin/libImath-3_2.dll', cls.runtime / 'libImath-3_2.dll')

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def read(self, seconds):
        return extra_geometry.alembic_scene_meshes(FLUID, seconds, IDENTITY, 'owner', 'Fluid', 'water', runtime=self.runtime)

    def test_the_fluid_comes_and_goes_with_its_samples(self):
        self.assertEqual(self.read(2.0), [])
        here = self.read(5.0)
        self.assertEqual(len(here), 1)
        mesh = here[0]
        self.assertEqual(mesh['identity'], 'owner|abc|/xf/StormMesh')
        self.assertEqual((len(mesh['vertices']), len(mesh['faces'])), (126139, 135547))
        self.assertEqual(len(mesh['velocities']), len(mesh['vertices']))
        self.assertTrue(all(0 <= i < len(mesh['vertices']) for face in mesh['faces'][:1000] for i in face))

    def test_it_blurs_along_its_velocities(self):
        fps = 24.0
        scene = {'fps': fps, 'camera': {'identity': 'cam', 'matrix': IDENTITY, 'focal_mm': 35}, 'meshes': self.read(120 / fps), 'lights': []}
        first, last = copy.deepcopy(scene), copy.deepcopy(scene)
        first['meshes'] = self.read(119.75 / fps)
        last['meshes'] = self.read(120.25 / fps)
        motion.apply_motion(scene, first, last, [-.25, .25])
        mesh = scene['meshes'][0]
        self.assertNotIn('velocities', mesh)
        held = self.read(120 / fps)[0]
        for k in (0, 1000, len(held['vertices']) - 1):
            for c in range(3):
                self.assertAlmostEqual(mesh['vertices_close'][k][c] - mesh['vertices'][k][c], held['velocities'][k][c] * .5 / fps, places=4)
        self.assertTrue(any('blurred along its velocities' in w for w in scene.get('warnings', [])))


class ImportedTimes(unittest.TestCase):
    """How a mesh from Modo's own Alembic import (File > Import) is found again in its file and timed."""

    def test_modo_writes_the_drive_without_its_slash(self):
        self.assertEqual(extra_geometry.alembic_path('C:Users/Raphael Tobar/Downloads/Mesher/Mesher.abc'),
                         Path('C:/Users/Raphael Tobar/Downloads/Mesher/Mesher.abc'))
        self.assertEqual(extra_geometry.alembic_path('D:/fluids/a.abc'), Path('D:/fluids/a.abc'))

    def test_played_once_the_time_runs_on(self):
        self.assertAlmostEqual(extra_geometry.alembic_seconds(5.0, 'Play-once', 0.0, 1.0, 2.8, 7.96), 5.0)
        self.assertAlmostEqual(extra_geometry.alembic_seconds(9.0, 'Play-once', 0.0, 1.0, 2.8, 7.96), 9.0)
        self.assertAlmostEqual(extra_geometry.alembic_seconds(2.0, 'Play-once', 1.0, 2.0, 2.8, 7.96), 5.0)

    def test_looped_and_bounced_within_the_samples(self):
        self.assertAlmostEqual(extra_geometry.alembic_seconds(9.0, 'Loop', 0.0, 1.0, 3.0, 8.0), 4.0)
        self.assertAlmostEqual(extra_geometry.alembic_seconds(9.0, 'Ping-pong', 0.0, 1.0, 3.0, 8.0), 7.0)

    def test_the_mesh_named_by_its_transform(self):
        read = [{'name': '/xf/StormMesh'}, {'name': '/spray/SprayMesh'}]
        self.assertIs(extra_geometry.alembic_match('xf', read), read[0])
        self.assertIs(extra_geometry.alembic_match('spray: SprayMesh', read), read[1])
        self.assertIsNone(extra_geometry.alembic_match('other', read))
        self.assertIs(extra_geometry.alembic_match('anything', read[:1]), read[0])


class ImportedSwitch(unittest.TestCase):
    def test_switched_off_modo_s_mesh_is_kept(self):
        from unittest import mock
        meshes = [{'identity': 'xf|evaluated_material_0|0'}]
        with mock.patch.dict(sys.modules, {'PySide2': None}), mock.patch.dict(os.environ, {'MOONRAY_MODO_ALEMBIC_IMPORT': '0'}):
            self.assertIs(extra_geometry.imported_alembic(meshes, 120, 24.0), meshes)

    def test_the_switch_is_in_the_overrides(self):
        kit = ROOT / 'kit/MoonRayForModo'
        self.assertIn('cmd moonray.pref.alembicImport ?', (kit / 'preferences.cfg').read_text(encoding='utf-8'))
        self.assertIn("lx.bless(switch('alembic_import'),'moonray.pref.alembicImport')", (kit / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8'))
        self.assertIn("'alembic_import': (True, bool)", (kit / 'python/moonray_modo/preferences.py').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
