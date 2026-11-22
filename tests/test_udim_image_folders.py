"""Modo's own UDIM sets (textures.folder_tiles, layers): an Image Folder of one image a tile, each image carrying its
tile's number, laid on by a layer whose Texture Locator has Use UDIM on. A tester's FBX import came in so; the kit
looked for one image with <UDIM> in its name, dropped the layers ('requires a still image or a <UDIM> filename'), and
MoonRay drew the model with no textures while Modo's viewport showed them."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import textures  # noqa: E402


class FolderTiles(unittest.TestCase):
    def setUp(self):
        self.place = tempfile.TemporaryDirectory()
        self.root = Path(self.place.name)
        self.images = self.root / 'imported_images'
        self.images.mkdir()
        self.cache = self.root / 'cache'
        patcher = mock.patch.object(textures, 'cache_root', lambda: self.cache)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.place.cleanup)

    def image(self, name, data=b'image'):
        path = self.images / name
        path.write_bytes(data)
        return path

    def test_named_by_their_numbers(self):
        clips = [(n, str(self.image('Tyrant_BaseColor.%d.png' % n))) for n in (1001, 1002, 1003)]
        self.image('Tyrant_Roughness.1001.png')
        pattern, tiles = textures.folder_tiles(clips)
        self.assertEqual(pattern.name, 'Tyrant_BaseColor.<UDIM>.png')
        self.assertEqual(sorted(tiles), [1001, 1002, 1003])
        self.assertEqual({n: p.name for n, p in textures.source_tiles(pattern).items()}, {n: p.name for n, p in tiles.items()})
        self.assertFalse(self.cache.exists())

    def test_named_otherwise_linked_by_number(self):
        clips = [(1001, str(self.image('skin_front.png', b'front'))), (1004, str(self.image('skin_back.png', b'back')))]
        pattern, tiles = textures.folder_tiles(clips)
        self.assertEqual(pattern.name, 'tile.<UDIM>.png')
        found = textures.source_tiles(pattern)
        self.assertEqual(sorted(found), [1001, 1004])
        self.assertEqual(found[1004].read_bytes(), b'back')

    def test_more_tiles_beside_them_than_the_set_has(self):
        # The folder on disk holds a tile the Image Folder does not: the set is the Image Folder's.
        clips = [(n, str(self.image('body.%d.exr' % n))) for n in (1001, 1002)]
        self.image('body.1003.exr')
        pattern, tiles = textures.folder_tiles(clips)
        self.assertEqual(sorted(textures.source_tiles(pattern)), [1001, 1002])

    def test_the_number_within_a_longer_one_is_not_taken(self):
        clips = [(1001, str(self.image('scan_21001.1001.png')))]
        pattern, _ = textures.folder_tiles(clips)
        self.assertEqual(pattern.name, 'scan_21001.<UDIM>.png')

    def test_refused(self):
        with self.assertRaisesRegex(ValueError, 'different file types'):
            textures.folder_tiles([(1001, str(self.image('a.png'))), (1002, str(self.image('b.exr')))])
        with self.assertRaisesRegex(ValueError, 'missing image'):
            textures.folder_tiles([(1001, str(self.images / 'gone.1001.png'))])
        with self.assertRaisesRegex(ValueError, 'from 1001'):
            textures.folder_tiles([(7, str(self.image('a.7.png')))])
        with self.assertRaisesRegex(ValueError, 'no images'):
            textures.folder_tiles([])


class LayerReading(unittest.TestCase):
    def test_the_layer_follows_its_image_folder(self):
        source = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/layers.py').read_text(encoding='utf-8')
        self.assertIn("next((i for i in connected if i.type=='imageFolder'),None)", source)
        self.assertIn("channel(locator,'useUDIM',0)", source)
        self.assertIn('textures.folder_tiles(', source)
        # The repeat modes an FBX import leaves (Reset) do not refuse the set.
        self.assertIn("tile = tile_v = 'repeat'", source)

    def test_an_image_folder_edit_is_a_material_edit(self):
        from moonray_modo import incremental
        self.assertIn('imageFolder', incremental.MATERIALS)


if __name__ == '__main__':
    unittest.main()
