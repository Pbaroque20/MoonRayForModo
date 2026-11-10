"""A MoonRay graph's images found as the scene's image clips are: where the graph says, beside the scene by their last
folders, or by name in exactly one folder the scene's own images are in. No Modo."""
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))

from moonray_modo import textures  # noqa: E402


def graph(*files):
    return {'root': 'out', 'nodes': {'out': {'type': 'DwaBaseMaterial', 'parameters': {}, 'inputs': {}},
                                     **{'n%d' % i: {'type': 'image', 'parameters': {'file': f, 'srgb': True}} for i, f in enumerate(files)}}}


class GraphImageRelink(unittest.TestCase):
    def setUp(self):
        self.folder = pathlib.Path(tempfile.mkdtemp())
        self.scene = self.folder / 'grass.lxo'
        self.images = self.folder / 'imported_images'
        self.images.mkdir()
        (self.images / 'albedo.jpg').write_bytes(b'x')

    def test_by_name_in_the_scenes_image_folder(self):
        made, changes = textures.relink_graph(graph('V:/Models/textures/2K_JPEG/albedo.jpg'), str(self.scene), [self.images])
        self.assertEqual(made['nodes']['n0']['parameters']['file'], str(self.images / 'albedo.jpg').replace('\\', '/'))
        self.assertEqual(changes[0][4], 'same name')

    def test_beside_the_scene_by_its_last_folders(self):
        (self.folder / '2K_JPEG').mkdir()
        (self.folder / '2K_JPEG' / 'rough.jpg').write_bytes(b'x')
        made, changes = textures.relink_graph(graph('V:/Models/textures/2K_JPEG/rough.jpg'), str(self.scene), [self.images])
        self.assertTrue(made['nodes']['n0']['parameters']['file'].endswith('2K_JPEG/rough.jpg'))
        self.assertEqual(changes[0][4], 'relocated')

    def test_an_image_where_it_says_is_left_alone(self):
        here = str(self.images / 'albedo.jpg')
        original = graph(here)
        made, changes = textures.relink_graph(original, str(self.scene), [self.images])
        self.assertIs(made, original)
        self.assertEqual(changes, [])

    def test_two_folders_with_the_name_is_no_guess(self):
        other = self.folder / 'more'
        other.mkdir()
        (other / 'albedo.jpg').write_bytes(b'x')
        made, changes = textures.relink_graph(graph('V:/x/albedo.jpg'), str(self.scene), [self.images, other])
        self.assertEqual(made['nodes']['n0']['parameters']['file'], 'V:/x/albedo.jpg')
        self.assertEqual(changes, [])
        listed = textures.missing_graph_images(graph('V:/x/albedo.jpg'), str(self.scene), [self.images, other])
        self.assertIsNone(listed[0][3])
        self.assertIn('more than one', listed[0][4])

    def test_only_the_scenes_folders_are_looked_in(self):
        made, changes = textures.relink_graph(graph('V:/x/albedo.jpg'), str(self.scene), [])
        self.assertEqual(changes, [])

    def test_listed_for_relink_images_with_its_offer(self):
        listed = textures.missing_graph_images(graph('V:/x/albedo.jpg', str(self.images / 'albedo.jpg')), str(self.scene), [self.images])
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0][:3], ('n0', 'file', 'V:/x/albedo.jpg'))
        self.assertTrue(listed[0][3].endswith('imported_images/albedo.jpg'))

    def test_what_names_an_image(self):
        self.assertTrue(textures.graph_image_value('a/b.JPG'))
        self.assertTrue(textures.graph_image_value('tile.<UDIM>.exr'))
        self.assertFalse(textures.graph_image_value('object'))
        self.assertFalse(textures.graph_image_value(1.0))


if __name__ == '__main__':
    unittest.main()
