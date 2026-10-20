"""Export as MoonRay Scene: textures collected beside the scene, and the split RDLA's Windows paths made readable."""
import sys
import tempfile
import types
import unittest
from pathlib import Path

for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
try:
    import PySide2  # noqa: F401
    stand_in = {}
except ImportError:
    # What is tested here needs no Qt: its window is given something to be made from, only while it is imported, so
    # that the other tests still find no Qt.
    qt = types.ModuleType('PySide2')
    qt.QtCore = types.ModuleType('PySide2.QtCore')
    qt.QtWidgets = types.ModuleType('PySide2.QtWidgets')
    qt.QtWidgets.QDialog = object
    stand_in = {'PySide2': qt, 'PySide2.QtCore': qt.QtCore, 'PySide2.QtWidgets': qt.QtWidgets}
sys.modules.update(stand_in)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
try:
    from moonray_modo import scene_export
except ImportError:
    scene_export = None
finally:
    for name in stand_in:
        sys.modules.pop(name, None)


@unittest.skipIf(scene_export is None, 'needs Qt')
class Collect(unittest.TestCase):
    def test_textures_are_copied_and_named_from_the_scene(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'maps').mkdir()
            texture = folder / 'maps' / 'wood.tx'
            texture.write_bytes(b'tx')
            for tile in (1001, 1002):
                (folder / 'maps' / ('skin.%d.tx' % tile)).write_bytes(b'tile')
            escaped = str(texture).replace('\\', '\\\\')
            udim = str(folder / 'maps' / 'skin.<UDIM>.tx').replace('\\', '\\\\')
            text = '["texture"] = "%s",\n["udim"] = "%s",\n["label"] = "not a file.tx",\n["other"] = "plain"' % (escaped, udim)
            scene = folder / 'out' / 'shot.rdla'
            scene.parent.mkdir()
            collected, count = scene_export.collect_textures(text, scene)
            self.assertEqual(count, 3)
            copies = sorted(p.name for p in (scene.parent / 'shot_textures').iterdir())
            self.assertEqual(len(copies), 3)
            self.assertIn('"shot_textures/', collected)
            self.assertNotIn(escaped, collected)
            self.assertIn('skin.<UDIM>.tx"', collected)
            self.assertIn('"not a file.tx"', collected)
            self.assertIn('"plain"', collected)


@unittest.skipIf(scene_export is None, 'needs Qt')
class Escaped(unittest.TestCase):
    def test_strings_from_the_converter_are_escaped_again(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'split.rdla'
            path.write_text(r'''ImageMap("/a") {
    ["texture"] = "C:\Users\me\a.tx",
    ["plain"] = "keep",
}
Metadata("/m") {
    {"cryptomatte/x/manifest", "string", "{"Mesh (2)":"39766e7d"}"},
}
''', encoding='utf-8')
            scene_export.escaped(path)
            text = path.read_text(encoding='utf-8')
            self.assertIn(r'["texture"] = "C:\\Users\\me\\a.tx",', text)
            self.assertIn(r'["plain"] = "keep",', text)
            self.assertIn(r'"{\"Mesh (2)\":\"39766e7d\"}"},', text)


@unittest.skipIf(scene_export is None, 'needs Qt')
class Binary(unittest.TestCase):
    def test_rdlb_leaves_only_the_rdlb_beside_the_scene(self):
        from unittest import mock
        read = []

        def convert(command, **_):
            source, output = Path(command[command.index('-i') + 1]), Path(command[command.index('-o') + 1])
            read.append((source.parent, source.read_text(encoding='utf-8')))
            output.write_bytes(b'rdlb')
            return mock.Mock(returncode=0)
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            with mock.patch.object(scene_export, 'converter', return_value=Path('rdl2_convert.exe')), \
                    mock.patch.object(scene_export.subprocess, 'run', convert), \
                    mock.patch('moonray_modo.native.environment', return_value={}):
                written = scene_export.write('SceneVariables {}', folder / 'scene.rdlb', 'rdlb', folder)
            self.assertEqual(written, [folder / 'scene.rdlb'])
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ['scene.rdlb'])
            self.assertEqual(read[0][1], 'SceneVariables {}')
            self.assertNotEqual(read[0][0], folder)
            self.assertFalse(read[0][0].exists())


if __name__ == '__main__':
    unittest.main()
