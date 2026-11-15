"""MoonLightIPR's pack converts the scene's textures side by side (conversions.together) and with the scene's colour
settings around them: from 2026-11-12 the wrapper that set them up shared the inner function's name, was replaced by it,
and every texture was converted one after another on Modo's thread (a tester saw one converter at a time)."""
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import conversions, moonlightipr_scene, textures  # noqa: E402


class PackTogether(unittest.TestCase):
    def test_the_inner_pack_runs_inside_together_and_the_colour_settings(self):
        seen = {}

        def inner(scene, *rest):
            seen['batch'] = conversions._batch.get()
            seen['policy'] = textures._policy.get()
            return b'', [], []
        settings = {'textures': {'config': '', 'rules': [{'path': 'C:/a.png', 'space': 'sRGB'}]}}
        with mock.patch.object(moonlightipr_scene, '_pack', inner), \
                mock.patch('moonray_modo.textures.configuration') as configured:
            configured.return_value.__enter__ = lambda self: None
            configured.return_value.__exit__ = lambda self, *exc: False
            moonlightipr_scene.pack({'asset_settings': settings, 'materials': {}, 'meshes': []}, 64, 36)
        self.assertIsNotNone(seen.get('batch'))
        configured.assert_called_once_with(settings)
        self.assertEqual(moonlightipr_scene._configured.__name__, '_configured')


if __name__ == '__main__':
    unittest.main()
