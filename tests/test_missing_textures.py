"""A texture the scene names that is not on this machine: the scene is written all the same, with an empty texture
path (or the image node's own default) in its place, and a notice naming it."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import map_library, textures


class MissingTextures(unittest.TestCase):
    def test_a_native_image_map_gets_an_empty_path_and_its_default(self):
        written = {}
        found = []
        with textures.noting_missing(found):
            map_library.emit('ImageMap', '/map', {'texture': r'C:\nowhere\gone.jpg'}, {},
                             lambda kind, path, attributes: written.update(attributes) or path)
        self.assertEqual(written['texture'], '""')
        self.assertEqual(written['use_default_color_when_missing'], 'true')
        self.assertEqual(found, [r'C:\nowhere\gone.jpg'])

    def test_missing_covers_files_and_udim_sets(self):
        self.assertTrue(textures.missing(r'C:\nowhere\gone.jpg'))
        self.assertTrue(textures.missing(r'C:\nowhere\skin.<UDIM>.tx'))
        self.assertFalse(textures.missing(__file__))


if __name__ == '__main__':
    unittest.main()
