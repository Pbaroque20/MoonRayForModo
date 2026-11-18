"""The scene's whole reading kept by the Scene cache for the next cold start (scene_reading): none kept or taken where
Modo cannot say the scene is unchanged; a kept one taken back as it was read; and refused where a file it names has
changed since."""
import pathlib
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import cache_folder, scene_reading  # noqa: E402


class SceneReading(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        cache_folder.forget()
        cache_folder._HELD.update(root=pathlib.Path(self.folder.name), scene=True)

    def tearDown(self):
        cache_folder.forget()
        self.folder.cleanup()

    def test_no_key_where_modo_cannot_be_asked(self):
        self.assertIsNone(scene_reading.key(True))

    def keep_and_wait(self, held_key, scene):
        scene_reading.keep(held_key, scene_reading.freeze(scene), scene)
        for _ in range(200):
            if list((pathlib.Path(self.folder.name) / 'Scenes').glob('*.bin')):
                return
            time.sleep(0.01)

    def test_a_kept_reading_comes_back_while_its_files_stand(self):
        scene = {'meshes': [{'name': 'car', 'vertices': [[0, 0, 0]]}], 'camera': {'focal_mm': 50}}
        with patch.object(scene_reading, 'files', return_value=[('a.png', [(0, 10, 1)])]):
            self.keep_and_wait(('scene', 1, 'x'), scene)
            self.assertEqual(scene_reading.load(('scene', 1, 'x')), scene)
            self.assertIsNone(scene_reading.load(('scene', 1, 'y')))

    def test_its_rows_can_be_hashed(self):
        # Modo's rows in a reading taken from the cache are hashed as they are when read from Modo: the hook that knows
        # them is loaded with the reading ("unmarshallable object" in a cold start that took one).
        # A fresh interpreter, where nothing has loaded evaluated yet, as at a cold start.
        import subprocess
        code = '''
import sys, pathlib, tempfile, pickle
sys.path.insert(0, %r)
from array import array
from moonray_modo import cache_folder, scene_reading
from moonray_modo.rows import Rows
cache_folder._HELD.update(root=pathlib.Path(tempfile.mkdtemp()), scene=True)
scene_reading.files = lambda scene: []
rows = Rows(array('f', [0.0, 1.0, 2.0]), 3, 'row:test')
cache_folder.keep('Scenes', ('k',), (pickle.dumps({'meshes': [{'vertices': rows}]}), []))
held = scene_reading.load(('k',))
from moonray_modo.scene_digest import content
print(content(held['meshes'][0]['vertices']))
''' % str(ROOT / 'kit/MoonRayForModo/python')
        done = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr[-600:])

    def test_refused_where_a_file_it_names_changed(self):
        scene = {'meshes': []}
        with patch.object(scene_reading, 'files', return_value=[('a.png', [(0, 10, 1)])]):
            self.keep_and_wait(('scene', 1, 'x'), scene)
        with patch.object(scene_reading, 'files', return_value=[('a.png', [(0, 11, 2)])]):
            self.assertIsNone(scene_reading.load(('scene', 1, 'x')))


class ReadingCode(unittest.TestCase):
    """A reading is kept by the code that makes it (host.py and what it imports), not the kit's installation: a kit
    installed again, or changed elsewhere, finds what it kept; one whose reading changed reads anew."""

    def digest(self, files):
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            package = pathlib.Path(folder) / 'moonray_modo'
            package.mkdir()
            for name, text in files.items():
                (package / name).write_text(text, encoding='utf-8')
            shutil.copyfile(scene_reading.__file__, package / 'scene_reading.py')
            namespace = {'__file__': str(package / 'scene_reading.py'), '__name__': 'scene_reading_copy'}
            exec(compile((package / 'scene_reading.py').read_text(encoding='utf-8'), str(package / 'scene_reading.py'), 'exec'), namespace)
            return namespace['reading_code']()

    def test_the_same_code_keeps_its_key(self):
        files = {'host.py': 'from .layers import x\n', 'layers.py': 'x = 1\n', 'panel.py': 'p = 1\n'}
        self.assertEqual(self.digest(files), self.digest(dict(files)))

    def test_a_change_outside_reading_keeps_it(self):
        files = {'host.py': 'from .layers import x\n', 'layers.py': 'x = 1\n', 'panel.py': 'p = 1\n'}
        self.assertEqual(self.digest(files), self.digest(dict(files, **{'panel.py': 'p = 2\n'})))

    def test_a_change_to_reading_changes_it(self):
        files = {'host.py': 'from . import layers, rows\n', 'layers.py': 'x = 1\n', 'rows.py': 'r = 1\n', 'panel.py': 'p = 1\n'}
        self.assertNotEqual(self.digest(files), self.digest(dict(files, **{'rows.py': 'r = 2\n'})))


class AdapterMark(unittest.TestCase):
    """A reading is kept by the geometry adapter that made it too (scene_reading.adapter_mark): a reading kept by the
    adapter before 0.5.5.1 was taken by 0.5.5.1's, the kit's code being the same, and showed a Group mask's material on
    every surface."""

    def mark(self, adapter=None, moment=None):
        """adapter_mark of a kit laid out as installed (MoonRayForModo/python/moonray_modo and MoonRayForModo/bin), its
        adapter of these bytes (none where None), modified at moment."""
        import os
        import shutil
        with tempfile.TemporaryDirectory() as folder:
            kit = pathlib.Path(folder) / 'MoonRayForModo'
            package = kit / 'python' / 'moonray_modo'
            package.mkdir(parents=True)
            shutil.copyfile(scene_reading.__file__, package / 'scene_reading.py')
            if adapter is not None:
                (kit / 'bin').mkdir()
                (kit / 'bin' / 'MoonRayGeometry.lx').write_bytes(adapter)
                if moment is not None:
                    os.utime(kit / 'bin' / 'MoonRayGeometry.lx', ns=(moment, moment))
            namespace = {'__file__': str(package / 'scene_reading.py'), '__name__': 'scene_reading_copy'}
            exec(compile((package / 'scene_reading.py').read_text(encoding='utf-8'), str(package / 'scene_reading.py'), 'exec'), namespace)
            return namespace['adapter_mark']()

    def test_the_same_adapter_keeps_its_mark(self):
        self.assertEqual(self.mark(b'adapter', 10 ** 18), self.mark(b'adapter', 10 ** 18))

    def test_another_adapter_has_another_mark(self):
        self.assertNotEqual(self.mark(b'adapter', 10 ** 18), self.mark(b'adapter, rebuilt', 10 ** 18))
        # Built again, the same size: a second later (Windows keeps file times to a tenth of a microsecond).
        self.assertNotEqual(self.mark(b'adapter', 10 ** 18), self.mark(b'adapter', 10 ** 18 + 10 ** 9))

    def test_no_adapter_is_a_mark_of_its_own(self):
        self.assertEqual(self.mark(), '-')
        self.assertNotEqual(self.mark(b'adapter', 10 ** 18), '-')

    def test_a_reading_is_kept_by_its_adapter(self):
        import types
        cache_folder.forget()
        cache_folder._HELD.update(root=pathlib.Path(tempfile.gettempdir()), scene=True)
        self.addCleanup(cache_folder.forget)
        with tempfile.TemporaryDirectory() as folder:
            scene = pathlib.Path(folder) / 'scene.lxo'
            scene.write_bytes(b'a scene')
            answers = {'query sceneservice scene.changed ? current': 0, 'query sceneservice scene.file ? current': str(scene)}
            lx = types.SimpleNamespace(eval1=answers.get, service=types.SimpleNamespace(
                Platform=lambda: types.SimpleNamespace(AppVersion=lambda: 1610, AppBuild=lambda: 9),
                Selection=lambda: types.SimpleNamespace(GetTime=lambda: 0.0)))
            host = types.SimpleNamespace(modo_displaces=lambda: True)
            keys = []
            with patch.dict(sys.modules, {'lx': lx, 'moonray_modo.host': host}):
                for mark in ('one adapter', 'one adapter', 'another'):
                    with patch.object(scene_reading, 'adapter_mark', return_value=mark):
                        keys.append(scene_reading.key(True))
        self.assertIsNotNone(keys[0])
        self.assertEqual(keys[0], keys[1])
        self.assertNotEqual(keys[0], keys[2])


if __name__ == '__main__':
    unittest.main()
