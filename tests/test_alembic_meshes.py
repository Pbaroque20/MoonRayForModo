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


if __name__ == '__main__':
    unittest.main()
