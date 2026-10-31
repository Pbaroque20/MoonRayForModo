"""Lights the camera sees, as MoonRay shows a light whose Visible in Camera is on: each local light's record says so
(MoonLightIPR's scene form N), a portal never; Modo's Visible to Camera and a MoonRay light's visible_in_camera forced
on both come through, and MoonRay's own scene is given the same."""
import pathlib
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import entities, moonlightipr_scene, rdla  # noqa: E402

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def seen(light):
    """What the record of one local light says of the camera (the number after its texture)."""
    _, local = moonlightipr_scene.lights({'lights': [light]}, [])
    return struct.unpack_from('<I20fiI', local[0])[-1]


def rect(**more):
    return dict({'kind': 'RectLight', 'identity': 'r', 'name': 'Rect', 'color': [1, 1, 1], 'intensity': 1.0, 'matrix': IDENTITY}, **more)


class LightSeen(unittest.TestCase):
    def test_a_light_set_visible_is_seen(self):
        self.assertEqual(seen(rect(camera_visible=True)), 1)
        self.assertEqual(seen(rect(kind='SphereLight', camera_visible=True)), 1)

    def test_a_light_is_hidden_unless_asked(self):
        self.assertEqual(seen(rect()), 0)
        self.assertEqual(seen(rect(camera_visible=False)), 0)

    def test_a_portal_is_never_seen(self):
        self.assertEqual(seen(rect(kind='PortalLight', camera_visible=True)), 0)

    def test_the_scene_form_says_so(self):
        scene = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 5, 1], 'focal_mm': 50.0, 'film_mm': 36.0},
                 'materials': {'': {'color': [.5, .5, .5]}}, 'meshes': [], 'lights': [rect(camera_visible=True)], 'environments': []}
        payload, _, _ = moonlightipr_scene.pack(scene, 64, 36, 0.0)
        self.assertEqual(payload[:4], b'MLSO')

    def test_a_moonray_light_forced_on_is_seen(self):
        for forced, expected in ((1, True), (0, False), (2, False)):
            entity = {'class': 'RectLight', 'name': 'Rect', 'identity': 'e', 'matrix': IDENTITY,
                      'parameters': {'visible_in_camera': forced}}
            preview = entities.preview({'camera': {'matrix': IDENTITY}, 'lights': [], 'environments': [], 'meshes': [],
                                        'entities': [entity]}, [])
            self.assertEqual(preview['lights'][0].get('camera_visible'), expected, forced)

    def test_moonray_is_given_a_modo_light_seen(self):
        scene = {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 5, 1], 'focal_mm': 50.0, 'film_mm': 36.0},
                 'materials': {'': {'color': [.5, .5, .5]}}, 'meshes': [], 'environments': []}
        self.assertIn('["visible_in_camera"] = 1', rdla.scene_text(dict(scene, lights=[rect(camera_visible=True)]), 64, 36, 1, 0.0))
        self.assertNotIn('["visible_in_camera"] = 1', rdla.scene_text(dict(scene, lights=[rect()]), 64, 36, 1, 0.0))


if __name__ == '__main__':
    unittest.main()
