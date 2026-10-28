"""The Scene cache: a heavy mesh simplified and packed for MoonLightIPR, or simplified for MoonRay's realtime, kept in the
cache folder and taken from it the next time, the same mesh in the same cut; nothing kept with it off; the folder kept
within its size; a preparation said as Caching scene... while it is on."""
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
sys.path.insert(0, str(ROOT / 'tests'))
from moonray_modo import cache_folder, moonlightipr_scene  # noqa: E402
from test_realtime_geometry import sphere  # noqa: E402


class SceneCache(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        cache_folder.forget()
        cache_folder._HELD.update(root=pathlib.Path(self.folder.name), scene=True)

    def tearDown(self):
        cache_folder.forget()
        self.folder.cleanup()

    def test_a_kept_value_comes_back_for_its_signature_alone(self):
        cache_folder.keep('Things', ('a', 1), b'value')
        self.assertEqual(cache_folder.kept('Things', ('a', 1)), b'value')
        self.assertIsNone(cache_folder.kept('Things', ('a', 2)))

    def test_off_keeps_nothing(self):
        cache_folder._HELD['scene'] = False
        cache_folder.keep('Things', ('a', 1), b'value')
        self.assertFalse(any(pathlib.Path(self.folder.name).rglob('*.bin')))

    def test_a_simplified_mesh_is_packed_once_for_every_session(self):
        mesh = sphere()
        mesh.pop('face_materials')
        cut = {'triangles': 1000, 'error': 0.01}
        # Another test may have packed the same sphere in this session already.
        moonlightipr_scene._packed.clear()
        first = moonlightipr_scene.mesh_payload(mesh, {'': 0}, {'': 0}, cut)
        self.assertEqual(len(list((pathlib.Path(self.folder.name) / 'MoonLightIPR/meshes').glob('*.bin'))), 1)
        # A session started again: nothing in memory, the mesh taken from the folder, not simplified again.
        moonlightipr_scene._packed.clear()
        with patch('moonray_modo.simplify.arrays', side_effect=AssertionError('simplified again')):
            self.assertEqual(moonlightipr_scene.mesh_payload(mesh, {'': 0}, {'': 0}, cut), first)

    def test_the_folder_is_kept_within_its_size(self):
        with patch.object(cache_folder, 'KEPT_BYTES', 300):
            for n in range(40):
                cache_folder.keep('Things', ('n', n), b'x' * 100)
        total = sum(entry.stat().st_size for entry in (pathlib.Path(self.folder.name) / 'Things').glob('*.bin'))
        self.assertLess(total, 40 * 100)


if __name__ == '__main__':
    unittest.main()
