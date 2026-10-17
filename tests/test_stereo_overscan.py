"""Stereo cameras and overscan from Modo's camera: the eye MoonRay renders and MoonLightIPR draws, and the windows of a
render to a file that goes past the frame."""
import math
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import rdla, stereo


def scene(**camera):
    held = {'matrix': rdla.IDENTITY, 'film_mm': 36.0, 'focal_mm': 50.0}
    held.update(camera)
    return {'camera': held, 'lights': [], 'materials': {}, 'meshes': [
        {'identity': 'floor', 'name': 'Floor', 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]], 'faces': [[0, 1, 2]],
         'material': '', 'matrix': rdla.IDENTITY}]}


STEREO = {'eye': 'both', 'interocular': 0.065, 'convergence': 2.0, 'composite': 'anaRedCyan'}


def camera_block(text):
    start = text.index('local camera = ')
    return text[start:text.index('\n}', start)]


class Stereo(unittest.TestCase):
    def test_both_eyes_preview_the_left(self):
        block = camera_block(rdla.scene_text(scene(stereo=dict(STEREO)), 64, 32))
        self.assertIn('["stereo_view"] = 1,', block)
        self.assertIn('["stereo_interocular_distance"] = 0.065,', block)
        self.assertIn('["stereo_convergence_distance"] = 2,', block)

    def test_a_render_may_ask_for_the_right_eye(self):
        value = dict(scene(stereo=dict(STEREO)), _stereo_eye='right')
        self.assertIn('["stereo_view"] = 2,', camera_block(rdla.scene_text(value, 64, 32)))

    def test_no_stereo_is_the_middle(self):
        self.assertNotIn('stereo_view', rdla.scene_text(scene(), 64, 32))

    def test_an_orthographic_camera_has_no_eye(self):
        value = scene(stereo=dict(STEREO), projection='ortho', ortho_width=2.0)
        self.assertNotIn('stereo_view', rdla.scene_text(value, 64, 32))
        self.assertFalse(stereo.both(value['camera']))

    def test_the_eye_is_placed_as_moonray_places_it(self):
        # MoonRay's PerspectiveCamera: the left eye half the interocular distance to the camera's left, its film
        # moved right by that half times the focal length over the convergence distance.
        left = stereo.placed(dict(scene(stereo=dict(STEREO))['camera']), {'_stereo_eye': 'left'})
        right = stereo.placed(dict(scene(stereo=dict(STEREO))['camera']), {'_stereo_eye': 'right'})
        self.assertAlmostEqual(left['matrix'][12], -0.0325)
        self.assertAlmostEqual(right['matrix'][12], 0.0325)
        self.assertAlmostEqual(left['film_offset'][0], 0.0325 * 50.0 / 2.0)
        self.assertAlmostEqual(right['film_offset'][0], -0.0325 * 50.0 / 2.0)

    def test_eye_files_sit_beside_the_one_chosen(self):
        self.assertEqual(stereo.eye_path(Path('C:/renders/shot.exr'), 'left'), Path('C:/renders/shot_left.exr'))

    def test_every_modo_composite_has_a_recipe(self):
        for kind in stereo.COMPOSITES:
            arguments = stereo.composite_arguments(kind, 'l.exr', 'r.exr', 'out.exr')
            self.assertEqual(arguments[-3:], ['--chappend', '-o', 'out.exr'])
        with self.assertRaises(ValueError):
            stereo.composite_arguments('stereoNone', 'l.exr', 'r.exr', 'out.exr')


class Overscan(unittest.TestCase):
    def test_a_render_to_a_file_goes_past_the_frame(self):
        text = rdla.scene_text(scene(overscan=1.2), 100, 50, 1, 0.1, 'out.exr')
        self.assertIn('["aperture_window"] = {0, 0, 100, 50},', text)
        self.assertIn('["region_window"] = {-10, -5, 110, 55},', text)

    def test_a_preview_shows_the_frame(self):
        self.assertNotIn('region_window', rdla.scene_text(scene(overscan=1.2), 100, 50))

    def test_none_without_overscan(self):
        self.assertNotIn('region_window', rdla.scene_text(scene(overscan=1.0), 100, 50, 1, 0.1, 'out.exr'))

    def test_a_render_region_is_counted_from_the_larger_picture(self):
        value = dict(scene(overscan=1.2), region=[0.0, 0.0, 0.5, 0.5])
        text = rdla.scene_text(value, 100, 50, 1, 0.1, 'out.exr')
        bounds = [int(v) for v in re.search(r'\["sub_viewport"\] = \{([^}]*)\}', text).group(1).split(',')]
        # The top-left quarter of the frame: 0..50 across, 25..50 up, moved by the margin of 10 and 5.
        self.assertEqual(bounds, [10, 30, 60, 55])


if __name__ == '__main__':
    unittest.main()
