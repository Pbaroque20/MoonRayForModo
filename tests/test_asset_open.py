"""A Modo scene in the asset library opens as a scene of its own (asset_import.action, working_copy), not merged into the
open one, where its sun and sky lit it beside the open scene's own; a scene that came with the kit opens from a copy."""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import asset_import, asset_library  # noqa: E402


class OpenScene(unittest.TestCase):
    def test_a_modo_scene_opens_and_a_model_is_brought_in(self):
        self.assertEqual(asset_import.action('Ocean at sunset.lxo'), 'Open Modo scene')
        self.assertEqual(asset_import.action('teapot.obj'), 'Import scene / model')

    def test_a_kit_scene_opens_from_a_new_copy_and_the_users_own_where_it_is(self):
        with tempfile.TemporaryDirectory() as folder:
            home, kit = pathlib.Path(folder) / 'home', pathlib.Path(folder) / 'library'
            kit.mkdir()
            scene = kit / 'Ocean at sunset.lxo'
            scene.write_bytes(b'LXOB')
            own = pathlib.Path(folder) / 'mine.lxo'
            own.write_bytes(b'LXOB')
            with mock.patch.object(asset_library, 'bundled', return_value=kit), mock.patch('pathlib.Path.home', return_value=home):
                first = asset_import.working_copy(scene)
                second = asset_import.working_copy(scene)
                self.assertEqual(asset_import.working_copy(own), own.resolve())
            self.assertEqual(first, home / 'Documents/MoonRay for Modo/Scenes/Ocean at sunset.lxo')
            self.assertEqual(second.name, 'Ocean at sunset 2.lxo')
            self.assertEqual(first.read_bytes(), b'LXOB')


if __name__ == '__main__':
    unittest.main()
