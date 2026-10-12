"""Portable bundles must accept multiple spellings of the same texture path."""
import json
import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import material_bundle, nodes

class BundlePaths(unittest.TestCase):
    def test_texture_aliases_share_relocatable_asset(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'sub').mkdir()
            texture = root / 'image.png'
            texture.write_bytes(b'original texture bytes')
            graph = nodes.new()
            for key, value in [('first', str(texture)), ('second', str(root / 'sub' / '..' / 'image.png'))]:
                graph['nodes'][key] = {'type': 'image', 'parameters': {'file': value}, 'inputs': {}, 'position': [0, 0]}
            entry = {'name': 'Aliases', 'settings': {'node_graph': graph, 'node_override': True}}
            manifest = material_bundle.save('root', lambda _: entry, root / 'bundle')
            saved = json.loads(manifest.read_text(encoding='utf-8'))
            self.assertEqual(len(saved['assets']), 1)
            shutil.move(str(manifest.parent), str(root / 'moved'))
            texture.unlink()
            loaded = material_bundle.load(root / 'moved/material.moonmat.json')
            held = loaded['materials']['material0']['settings']['node_graph']['nodes']
            self.assertEqual(held['first']['parameters']['file'], held['second']['parameters']['file'])
            self.assertEqual(Path(held['first']['parameters']['file']).read_bytes(), b'original texture bytes')

    def test_udim_aliases_and_distinct_same_named_files(self):
        resolve = Path.resolve
        def windows_resolve(path, *args, **kwargs):
            if '<UDIM>' in path.name:
                raise OSError(123, 'Windows rejects a pattern as a literal filename')
            return resolve(path, *args, **kwargs)
        with mock.patch.object(Path, 'resolve', windows_resolve), tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'sub').mkdir()
            (root / 'other').mkdir()
            (root / 'image.1001.png').write_bytes(b'tile one')
            (root / 'image.1002.png').write_bytes(b'tile two')
            (root / 'other/image.1001.png').write_bytes(b'different texture')
            paths = [str(root / 'image.<UDIM>.png'), str(root / 'sub/../image.<UDIM>.png'), str(root / 'other/image.1001.png')]
            if os.name == 'nt':
                paths.append(paths[0].upper())
            graph = nodes.new()
            for i, value in enumerate(paths):
                graph['nodes']['image' + str(i)] = {'type': 'image', 'parameters': {'file': value}, 'inputs': {}, 'position': [0, 0]}
            entry = {'name': 'Tiles', 'settings': {'node_graph': graph, 'node_override': True}}
            manifest = material_bundle.save('root', lambda _: entry, root / 'bundle')
            saved = json.loads(manifest.read_text(encoding='utf-8'))
            self.assertEqual(len(saved['assets']), 3)
            loaded = material_bundle.load(manifest)
            held = loaded['materials']['material0']['settings']['node_graph']['nodes']
            self.assertEqual(held['image0']['parameters']['file'], held['image1']['parameters']['file'])
            self.assertEqual(Path(held['image2']['parameters']['file']).read_bytes(), b'different texture')
            if os.name == 'nt':
                self.assertEqual(held['image0']['parameters']['file'], held['image3']['parameters']['file'])

    def test_failed_copy_cleans_only_its_staging_and_can_retry(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            texture = root / 'image.png'
            texture.write_bytes(b'original texture bytes')
            unrelated = root / 'bundle.partial-existing'
            unrelated.mkdir()
            (unrelated / 'keep.txt').write_text('keep me', encoding='utf-8')
            graph = nodes.new()
            graph['nodes']['image'] = {'type': 'image', 'parameters': {'file': str(texture)}, 'inputs': {}, 'position': [0, 0]}
            entry = {'name': 'Retry', 'settings': {'node_graph': graph, 'node_override': True}}
            copy = shutil.copy2
            def fail_after_copy(source, target):
                copy(source, target)
                raise OSError('simulated disk failure')
            with mock.patch.object(material_bundle.shutil, 'copy2', side_effect=fail_after_copy):
                with self.assertRaisesRegex(OSError, 'simulated disk failure'):
                    material_bundle.save('root', lambda _: entry, root / 'bundle')
            self.assertFalse((root / 'bundle').exists())
            self.assertEqual(set(root.glob('bundle.partial-*')), {unrelated})
            self.assertEqual((unrelated / 'keep.txt').read_text(encoding='utf-8'), 'keep me')
            self.assertEqual(texture.read_bytes(), b'original texture bytes')
            manifest = material_bundle.save('root', lambda _: entry, root / 'bundle')
            self.assertEqual(material_bundle.load(manifest)['root'], 'material0')

    def test_failed_publish_preserves_existing_destination(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            destination = root / 'bundle'
            entry = {'name': 'Race', 'settings': {'native_shader': 'DwaBaseMaterial', 'native_parameters': {}}}
            def concurrent_destination(source, target):
                destination.mkdir()
                (destination / 'keep.txt').write_text('another save', encoding='utf-8')
                raise FileExistsError('destination appeared')
            with mock.patch.object(Path, 'rename', concurrent_destination):
                with self.assertRaises(FileExistsError):
                    material_bundle.save('root', lambda _: entry, destination)
            self.assertEqual((destination / 'keep.txt').read_text(encoding='utf-8'), 'another save')
            self.assertEqual(list(root.glob('bundle.partial-*')), [])

if __name__ == '__main__':
    unittest.main()
