import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))

from moonray_modo import entities


def lines(name, parameters):
    entity = {'identity': 'cam', 'name': 'cam', 'class': name, 'parameters': parameters}
    return entities.camera_lines({'entities': [entity]}, entity)


class CameraNear(unittest.TestCase):
    def test_a_camera_left_at_moonrays_near_sees_as_near_as_a_modo_camera(self):
        self.assertIn('  ["near"] = 0.001,', lines('PerspectiveCamera', {}))

    def test_a_near_the_user_set_is_kept(self):
        written = lines('PerspectiveCamera', {'near': 0.5})
        self.assertEqual([line for line in written if '"near"' in line], ['  ["near"] = 0.5,'])

    def test_a_new_camera_shows_the_near_it_renders_with(self):
        self.assertEqual(entities.starting('PerspectiveCamera')['near'], entities.CAMERA_NEAR)

    def test_a_bake_camera_has_no_view_to_clip(self):
        self.assertFalse(any('"near"' in line for line in lines('BakeCamera', {'geometry': 'x'})))


if __name__ == '__main__':
    unittest.main()
