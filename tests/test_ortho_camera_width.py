"""An orthographic Modo camera sees as wide as its film, as fitted, at its Focus Distance through its lens (camera.ortho_width),
as Modo renders it (tools/probe_cl_ortho_camera.py, checked against Modo's renders: a square picture, 50 mm, Focus
Distance 6, Target Distance 2, sees 2.88 across). A report: the plugin went by the Target Distance, and a camera whose two
distances differ came out zoomed in MoonLightIPR and MoonRay."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo.camera import framing, ortho_width  # noqa: E402


class OrthoWidth(unittest.TestCase):
    def test_by_focus_distance(self):
        aperture, _ = framing(400, 400, .036, .024)
        self.assertAlmostEqual(ortho_width(aperture, 6.0, .05), 2.88)

    def test_by_focal_length(self):
        aperture, _ = framing(400, 400, .036, .024)
        self.assertAlmostEqual(ortho_width(aperture, 4.0, .1), .96)

    def test_a_wide_picture_by_the_film_width(self):
        aperture, _ = framing(800, 400, .036, .024)
        self.assertAlmostEqual(ortho_width(aperture, 4.0, .05), 2.88)


if __name__ == '__main__':
    unittest.main()
