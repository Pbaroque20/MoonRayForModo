"""Network textures must participate in missing-asset and change reporting."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import assets, textures

class NetworkAssets(unittest.TestCase):
    def test_unc_assets_including_light_files_are_found(self):
        image = r'\\server\share\image.<UDIM>.exr'
        cookie = r'\\server\share\cookie.tx'
        volume = r'\\server\share\filter.vdb'
        scene = {'materials': {'paint': {'file': image}},
                 'production': {'lights': {'key': {'cookie_file': cookie, 'filter_vdb': volume}}},
                 'warnings': [r'\\server\share\not-an-asset.png']}
        self.assertEqual(assets.paths(scene), sorted([image, cookie, volume]))
        with mock.patch.object(textures, 'source_tiles', return_value={}) as lookup:
            report = assets.inventory(scene)
        self.assertEqual({r['path'] for r in report}, {image, cookie, volume})
        self.assertTrue(all(r['missing'] and r['tiles'] == 0 for r in report))
        self.assertEqual(lookup.call_count, 3)

    def test_network_texture_changes_affect_signature(self):
        image = r'\\server\share\image.tx'
        tile = mock.Mock()
        tile.__str__ = mock.Mock(return_value=image)
        scene = {'material': {'file': image}}
        with mock.patch.object(textures, 'source_tiles', return_value={0: tile}):
            tile.stat.return_value = SimpleNamespace(st_size=10, st_mtime_ns=100)
            before = assets.signature(scene)
            tile.stat.return_value = SimpleNamespace(st_size=12, st_mtime_ns=200)
            after = assets.signature(scene)
        self.assertEqual(len(before), 1)
        self.assertNotEqual(before, after)

    def test_local_and_forward_unc_paths_still_work(self):
        paths = ['C:/textures/a.png', 'C:\\textures\\b.tx', '//server/share/c.exr']
        self.assertEqual(assets.paths({'files': paths + ['relative.png', 'plain text']}), sorted(paths))

if __name__ == '__main__':
    unittest.main()
