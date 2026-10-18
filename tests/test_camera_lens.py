"""MoonRay's cameras framed in Modo's viewport: the Modo lens worked out from each camera's MoonRay one."""
import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import entities
from moonray_modo.camera import offsets


def values(**given):
    return lambda key: float(given[key])


def across(lens):
    """The view's width in degrees, horizontally, for a perspective lens."""
    return math.degrees(2 * math.atan(lens['apertureX'] / 2 / lens['focalLen']))


class Lens(unittest.TestCase):
    def test_perspective_keeps_moonrays_view(self):
        lens = entities.modo_lens('PerspectiveCamera', values(focal=30, film_width_aperture=24, horizontal_film_offset=2, vertical_film_offset=-1))
        moonray = math.degrees(2 * math.atan(24 / 2 / 30))
        self.assertAlmostEqual(across(lens), moonray, places=6)
        self.assertEqual((lens['projType'], lens['filmFit']), ('persp', 'horizontal'))
        # The plugin turns a Modo film offset into MoonRay's (camera.offsets); this is the way back.
        self.assertEqual([round(v, 6) for v in offsets(lens['offsetX'], lens['offsetY'], 'persp', lens['apertureX'], 1.0)], [2.0, -1.0])

    def test_orthographic_is_as_wide_as_its_film(self):
        for target in (1.0, 4.0):
            lens = entities.modo_lens('OrthographicCamera', values(film_width_aperture=10, horizontal_film_offset=1.5, vertical_film_offset=0), target)
            self.assertEqual(lens['projType'], 'ortho')
            width = lens['apertureX'] * target / lens['focalLen']
            self.assertAlmostEqual(width, 10.0)
            self.assertAlmostEqual(offsets(lens['offsetX'], lens['offsetY'], 'ortho', lens['apertureX'], width)[0], 1.5)

    def test_wide_cameras_show_as_wide_as_the_viewport_goes(self):
        self.assertAlmostEqual(across(entities.modo_lens('DomeMaster3DCamera', values(FOV_horizontal_angle=60))), 60.0)
        self.assertAlmostEqual(across(entities.modo_lens('FisheyeCamera', values(fov=180))), entities.WIDEST_VIEW)
        self.assertAlmostEqual(across(entities.modo_lens('SphericalCamera', values(min_longitude=-45, max_longitude=45))), 90.0)

    def test_every_viewed_camera_is_a_moonray_camera_with_its_inputs(self):
        for name in entities.VIEWED_CAMERAS:
            self.assertEqual(entities.catalog()[name]['category'], 'camera')
            self.assertTrue(set(entities.lens_inputs(name)) <= set(entities.catalog()[name]['attributes']), name)
        self.assertNotIn('BakeCamera', entities.VIEWED_CAMERAS)


if __name__ == '__main__':
    unittest.main()
