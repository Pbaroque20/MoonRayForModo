"""XPU2 takes a scene with Limit Geometry Resolution on (enable_max_geometry_resolution): a tester's car scene went to
MoonRay XPU with "__SceneVariables__ / enable_max_geometry_resolution: nondefault setting unsupported". MoonRay's own
geometry reads neither setting; the kit applies the cap to the meshes' resolutions it writes, so XPU2 is handed the same
capped meshes as MoonRay is."""
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class GeometryResolutionLimit(unittest.TestCase):
    def test_xpu2_accepts_the_switch_and_the_limit(self):
        text = (ROOT / 'xpu2/interactive/cpu_scene.h').read_text(encoding='utf-8')
        accepted = text[text.index('attributes(sv,{'):]
        accepted = accepted[:accepted.index('});')]
        for name in ('enable_max_geometry_resolution', 'max_geometry_resolution'):
            self.assertIn('"%s"' % name, accepted)

    def test_the_kit_applies_the_cap_itself(self):
        rdla = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/rdla.py').read_text(encoding='utf-8')
        self.assertRegex(rdla, re.escape("resolution_cap = held_render['max_geometry_resolution'] if "
                                         "held_render['enable_max_geometry_resolution'] else None"))


if __name__ == '__main__':
    unittest.main()
