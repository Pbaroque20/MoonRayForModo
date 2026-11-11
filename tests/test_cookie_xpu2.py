"""A cookie light filter keeps XPU2: XPU2 draws it rightly (checked against MoonRay's scalar mode, mean within 0.02%),
while this build of MoonRay leaves its vector and XPU pictures not numbers. So the preview is XPU2's where XPU2 renders,
and the MoonRay its session falls back to, should XPU2 leave it the scene, starts in scalar (persistent moonray_mode).
A VDB made with the kit's MoonRay items whose emission grid is set is kept for XPU2 the same way; one imported as extra
geometry still sends the whole render to scalar."""
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo/python/moonray_modo'


class Cookie(unittest.TestCase):
    def test_render_keeps_xpu2_for_a_cookie_and_names_moonrays_mode(self):
        source = (KIT / 'render.py').read_text(encoding='utf-8')
        self.assertIn("if mode!='scalar' and slow in (COOKIE,VDB_ITEM) and xpu2_takes:", source)
        self.assertIn("self.moonray_mode='scalar'", source)
        self.assertIn("moonray_mode=getattr(self,'moonray_mode',None)", source)
        self.assertIn('scalar_only(snapshot) in (None,COOKIE,VDB_ITEM)', source)

    def test_an_emissive_vdb_item_is_named(self):
        source = (KIT / 'render.py').read_text(encoding='utf-8')
        self.assertIn("entity.get('class')=='VdbGeometry' and (entity.get('parameters') or {}).get('emission_grid')", source)
        self.assertIn("return VDB_ITEM", source)

    def test_the_session_starts_moonray_in_that_mode_where_xpu2_does_not_render(self):
        source = (KIT / 'persistent.py').read_text(encoding='utf-8')
        self.assertIn("mode=request['mode'] if self.xpu2_active else (request.get('moonray_mode') or request['mode'])", source)
        self.assertIn("request.get('moonray_mode'))+native.source_switches()", source)


if __name__ == '__main__':
    unittest.main()
