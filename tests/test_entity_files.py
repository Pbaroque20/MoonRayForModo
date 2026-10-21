import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import entities


def light(texture):
    return {'identity': 'light', 'name': 'Window light', 'class': 'RectLight', 'parameters': {'texture': texture, 'intensity': 5.0}}


class EntityFiles(unittest.TestCase):
    def test_a_light_texture_that_is_nowhere_is_left_out_and_said(self):
        warnings = []
        held = entities.located(light('C:/Users/Someone/Desktop/Imported Images/blinds.jpg'), None, warnings)
        self.assertNotIn('texture', held['parameters'])
        self.assertEqual(held['parameters']['intensity'], 5.0)
        self.assertEqual(len(warnings), 1)
        self.assertIn('blinds.jpg', warnings[0])

    def test_a_light_texture_moved_with_the_scene_is_found_beside_it(self):
        with tempfile.TemporaryDirectory() as folder:
            images = pathlib.Path(folder) / 'Imported Images'
            images.mkdir()
            (images / 'blinds.jpg').write_bytes(b'not really a picture')
            warnings = []
            held = entities.located(light('C:/Users/Someone/Desktop/Imported Images/blinds.jpg'),
                                    str(pathlib.Path(folder) / 'scene.lxo'), warnings)
            self.assertEqual(pathlib.Path(held['parameters']['texture']), images / 'blinds.jpg')
            self.assertEqual(warnings, [])

    def test_a_texture_that_is_there_is_kept_as_it_is(self):
        with tempfile.TemporaryDirectory() as folder:
            picture = pathlib.Path(folder) / 'blinds.jpg'
            picture.write_bytes(b'x')
            entity = light(str(picture))
            self.assertIs(entities.located(entity, None, []), entity)


if __name__ == '__main__':
    unittest.main()
