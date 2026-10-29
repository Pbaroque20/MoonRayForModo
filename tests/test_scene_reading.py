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


if __name__ == '__main__':
    unittest.main()
