"""MoonLightIPR's own Clamp From Bounce: 0 unless the scene says otherwise, packed into its scene in place of MoonRay's
sample_clamping_depth, which MoonRay's own scene keeps; and shown in the MoonLightIPR group of Render Settings."""
import pathlib
import struct
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_scene, scene_settings  # noqa: E402
import importlib.util  # noqa: E402
scene_setup = importlib.util.find_spec("moonray_modo.scene_setup")


def packed_depth(scene):
    payload, _, _ = moonlightipr_scene.pack(scene, 64, 36, 0.0)
    # After the mark (4 bytes) and the eight numbers of size, depths and samples: the sample clamp, then its bounce.
    return struct.unpack_from('<fI', payload, 36)


def scene(**more):
    return dict({'camera': {'matrix': [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 1, 5, 1], 'focal_mm': 50.0, 'film_mm': 36.0},
                 'materials': {'': {'color': [.5, .5, .5]}}, 'meshes': [], 'lights': [], 'environments': [],
                 'render_settings': {'sample_clamping_value': 2.0, 'sample_clamping_depth': 1}}, **more)


class ClampDepth(unittest.TestCase):
    def test_default_is_zero(self):
        self.assertEqual(scene_settings.DEFAULTS['moonlightipr']['clamp_depth'], 0)
        self.assertEqual(packed_depth(scene()), (2.0, 0))

    def test_the_scene_choice_is_packed_and_moonray_keeps_its_own(self):
        values = scene_settings.complete({'moonlightipr': {'clamp_depth': 2}, 'render': {'sample_clamping_depth': 1}})
        self.assertEqual(values['moonlightipr']['clamp_depth'], 2)
        self.assertEqual(values['render']['sample_clamping_depth'], 1)
        # As scene_setup.configure puts it on the scene (it needs Modo to run whole).
        held = scene(_moonlightipr_clamp_depth=values['moonlightipr']['clamp_depth'])
        self.assertEqual(packed_depth(held), (2.0, 2))
        self.assertIn("scene['_moonlightipr_clamp_depth']", pathlib.Path(scene_setup.origin).read_text(encoding='utf-8'))

    def test_shown_in_the_moonlightipr_group(self):
        group = next(entries for name, _, entries in scene_settings.GROUPS if name == 'MoonLightIPR')
        self.assertIn(('moonlightipr', 'clamp_depth'), [entry['path'] for entry in group])
        self.assertNotIn(('render', 'sample_clamping_depth'), [entry['path'] for entry in group])


if __name__ == '__main__':
    unittest.main()
