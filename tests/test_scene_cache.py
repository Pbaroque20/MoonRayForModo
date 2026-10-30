"""The Scene cache: a heavy mesh simplified and packed for MoonLightIPR, or simplified for MoonRay's realtime, kept in the
cache folder and taken from it the next time, the same mesh in the same cut; nothing kept with it off; the folder kept
within its size; what it did counted apart, so that the status says Caching scene... only while it keeps, and Loading
scene from cache... while it reads back."""
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

    def test_clear_empties_what_the_kit_keeps_alone(self):
        # Clear Cache: the kit's own folders emptied; a file of the user's in a cache folder they chose is not touched.
        base = pathlib.Path(self.folder.name)
        cache_folder.keep('Scenes', ('k',), (b'reading', []))
        (base / 'Textures').mkdir()
        (base / 'Textures' / 'a.tx').write_bytes(b'x' * 100)
        (base / 'MoonLightIPR' / 'meshes').mkdir(parents=True)
        (base / 'MoonLightIPR' / 'meshes' / 'b.bin').write_bytes(b'y' * 10)
        (base / 'notes.txt').write_text('mine')
        (base / 'Diagnostics').mkdir()
        (base / 'Diagnostics' / 'log.txt').write_text('log')
        removed, freed, left = cache_folder.clear()
        self.assertEqual((removed, left), (3, 0))
        self.assertGreaterEqual(freed, 110)
        self.assertFalse(any((base / kind).exists() for kind in cache_folder.CLEARED))
        self.assertEqual((base / 'notes.txt').read_text(), 'mine')
        self.assertTrue((base / 'Diagnostics' / 'log.txt').is_file())
        self.assertIsNone(cache_folder.kept('Scenes', ('k',)))

    def test_what_it_did_is_counted_apart(self):
        # Caching scene... where something was not kept and is made now; Loading scene from cache... where it was.
        cache_folder.keep('Things', ('a', 1), b'value')
        missed, found = cache_folder.missed(), cache_folder.found()
        cache_folder.kept('Things', ('a', 1))
        self.assertEqual((cache_folder.missed(), cache_folder.found()), (missed, found + 1))
        cache_folder.kept('Things', ('b', 1))
        self.assertEqual((cache_folder.missed(), cache_folder.found()), (missed + 1, found + 1))

    def test_a_kept_reading_is_told_before_it_is_taken(self):
        from moonray_modo import scene_reading
        self.assertFalse(scene_reading.held(('k',)))
        self.assertFalse(scene_reading.held(None))
        cache_folder.keep('Scenes', ('k',), (b'', []))
        self.assertTrue(scene_reading.held(('k',)))

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
