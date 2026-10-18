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

    def test_gate_lies_on_the_pictures_edges(self):
        # A 24 mm film at 30 mm, 16:9: at depth 2 the outline is 1.6 across, 0.9 high, centred, in front of the camera.
        points = entities.gate('persp', .030, .024, 0.0, 0.0, 4.0, 16 / 9, depth=2.0)
        xs, ys, zs = zip(*points)
        self.assertEqual(points[0], points[-1])
        self.assertAlmostEqual(max(xs) - min(xs), 1.6)
        self.assertAlmostEqual(max(ys) - min(ys), .9)
        self.assertEqual(set(zs), {-2.0})
        # An orthographic view is as wide as its film times its target over its focal length, at any depth; an offset
        # moves the outline by as much of it as the offset is of the film.
        points = entities.gate('ortho', .05, .075, .0375, 0.0, 4.0, 2.0, depth=1.0)
        xs = [p[0] for p in points]
        self.assertAlmostEqual(max(xs) - min(xs), 6.0)
        self.assertAlmostEqual((max(xs) + min(xs)) / 2, 3.0)

    def test_margins_surround_the_gate_without_covering_it(self):
        outline = entities.gate('persp', .030, .024, 0.0, 0.0, 4.0, 16 / 9, depth=2.0)
        margins = entities.gate_margins(outline)
        self.assertEqual(len(margins), 4)
        inside = lambda x, y, quad: min(p[0] for p in quad) < x < max(p[0] for p in quad) and min(p[1] for p in quad) < y < max(p[1] for p in quad)
        # The picture's middle is in none of them; just past each edge, and at a corner, is in one.
        self.assertFalse(any(inside(0.0, 0.0, quad) for quad in margins))
        for x, y in ((.81, 0.0), (-.81, 0.0), (0.0, .46), (0.0, -.46), (.81, .46)):
            self.assertEqual(sum(inside(x, y, quad) for quad in margins), 1, (x, y))
        self.assertTrue(all(p[2] == -2.0 for quad in margins for p in quad))

    def test_every_viewed_camera_is_a_moonray_camera_with_its_inputs(self):
        for name in entities.VIEWED_CAMERAS:
            self.assertEqual(entities.catalog()[name]['category'], 'camera')
            self.assertTrue(set(entities.lens_inputs(name)) <= set(entities.catalog()[name]['attributes']), name)
        self.assertNotIn('BakeCamera', entities.VIEWED_CAMERAS)


if __name__ == '__main__':
    unittest.main()
