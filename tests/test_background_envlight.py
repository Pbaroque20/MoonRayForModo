"""Render Settings > Camera Background (Black, Solid color, Image) overrides MoonRay's EnvLight items as it does Modo's
environments: the camera no longer sees them, they still light the scene, in MoonRay XPU and XPU2 (the scene's EnvLight
visible_in_camera) and MoonLightIPR (its background part)."""
import pathlib
import struct
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import background, entities, moonlightipr_scene, rdla  # noqa: E402

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def scene():
    return {'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 5, 1], 'focal_mm': 50.0, 'film_mm': 36.0},
            'materials': {'': {'color': [.5, .5, .5]}}, 'meshes': [], 'lights': [], 'environments': [],
            'entities': [{'identity': 'env', 'name': 'Dome', 'class': 'EnvLight', 'matrix': IDENTITY,
                          'parameters': {'color': [1.0, 1.0, 1.0], 'visible_in_camera': 1}}]}


def seen(parts):
    rows = moonlightipr_scene.ENVIRONMENT_ROWS
    return {name: struct.unpack('<%df' % (rows * 3), parts[1 + i])[rows // 2 * 3] for i, name in enumerate(moonlightipr_scene.ENVIRONMENT_PARTS)}


class BackgroundOverridesEnvLight(unittest.TestCase):
    def test_left_to_the_environment_the_envlight_is_seen(self):
        s = scene()
        background.apply(s, {'mode': 'environment'})
        self.assertEqual(s['entities'][0]['parameters']['visible_in_camera'], 1)

    def test_black_colour_and_image_hide_it_from_the_camera_in_every_engine(self):
        for mode in ('black', 'color'):
            s = scene()
            background.apply(s, {'mode': mode, 'color': '#336699'})
            self.assertEqual(s['entities'][0]['parameters']['visible_in_camera'], 0, mode)
            # MoonRay XPU and XPU2 read the scene text.
            text = rdla.scene_text(s, 64, 36, 1, 0.0)
            self.assertIn('EnvLight("/modo/entity/env")', text)
            block = text[text.index('EnvLight("/modo/entity/env")'):]
            self.assertIn('["visible_in_camera"] = 0', block[:block.index('}')], mode)
            # MoonLightIPR: lit by it, the camera sees only the background chosen.
            preview = entities.preview(s, [])
            parts = seen(moonlightipr_scene.environment_section(preview, 0.0, [], None))
            self.assertGreater(parts['lighting'], 0.9, mode)
            self.assertAlmostEqual(parts['background'], 0.0 if mode == 'black' else parts['background'], msg=mode)
            dome = [e for e in preview['environments'] if e.get('identity') == 'env'][0]
            self.assertFalse(dome['camera'], mode)

    def test_a_solid_colour_stays_behind_an_envlight_replacing_modos_environments(self):
        """An EnvLight replacing Modo's environments (as a new one does) dropped every one of them, the camera background
        too: Solid color came out black. The background stays, seen by the camera alone."""
        s = scene()
        s['entities'][0]['parameters']['modo_replace_environment'] = True
        s['environments'] = [{'kind': 'constant', 'name': 'Modo', 'intensity': 1.0, 'zenith': [0, 1, 0], 'nadir': [0, 1, 0]}]
        background.apply(s, {'mode': 'color', 'color': '#ffffff', 'intensity': 0.5})
        # MoonRay XPU and XPU2: the backdrop written, the Modo environment not.
        text = rdla.scene_text(s, 64, 36, 1, 0.0)
        self.assertIn('/modo/environment/scene/0', text)
        self.assertNotIn('/modo/environment/scene/1', text)
        block = text[text.index('EnvLight("/modo/environment/scene/0")'):]
        block = block[:block.index('}')]
        self.assertIn('["visible_in_camera"] = 1', block)
        self.assertIn('["visible_diffuse_reflection"] = false', block)
        # MoonLightIPR: the camera sees the colour; the EnvLight lights the scene.
        parts = seen(moonlightipr_scene.environment_section(entities.preview(s, []), 0.0, [], None))
        self.assertAlmostEqual(parts['background'], 0.5, places=4)
        self.assertGreater(parts['lighting'], 0.9)

    def test_the_scene_given_is_not_changed_underneath(self):
        s = scene()
        held = s['entities'][0]
        background.apply(s, {'mode': 'black'})
        self.assertEqual(held['parameters']['visible_in_camera'], 1)


if __name__ == '__main__':
    unittest.main()
