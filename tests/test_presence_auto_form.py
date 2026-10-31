"""Automatic Presence Shadows greys Presence Shadows at once, in the render settings and on lights, and a light's own value is
then not written; and Realtime Sample % in the preview's preferences as in the render settings."""
import pathlib
import re
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
from moonray_modo import entities, presence_shadows


class Refresh(unittest.TestCase):
    def test_the_switch_tells_the_forms(self):
        commands = (KIT / 'lxserv/moonray_preferences.py').read_text(encoding='utf-8')
        self.assertIn("switch('presence_shadows_auto',render_settings_changed)", commands)
        self.assertRegex(commands, r'def render_settings_changed\(\):[\s\S]*?property_notifications\.notify\(\)')
        self.assertRegex(commands, r'held\(\)\.set\(key,bool\(self\.dyna_Int\(0\)\)\)\s+if changed:changed\(\)')

    def test_the_render_settings_follow_and_grey_it(self):
        form = (KIT / 'lxserv/moonray_render_settings.py').read_text(encoding='utf-8')
        self.assertIn("(property_notifications.NAME,'')", form)
        self.assertTrue(re.search(r"entry\['key'\]=='enable_presence_shadows'[\s\S]*?return not automatic\(\)", form))

    def test_a_lights_popup_follows_and_greys_it(self):
        form = (KIT / 'lxserv/moonray_entities.py').read_text(encoding='utf-8')
        self.assertIn("automatic=key=='presence_shadows'", form)
        self.assertIn('ALSO=(property_notifications.NAME,) if automatic else ()', form)
        self.assertRegex(form, r'if automatic:[\s\S]*?if presence_automatic\(\):return False')
        self.assertIn('for notifier in self.ALSO:self._notifications.add(notifier,', form)


class Written(unittest.TestCase):
    SCENE = {'entities': [{'class': 'RectLight', 'identity': 'a', 'name': 'a', 'parameters': {'presence_shadows': 1, 'width': 2.0}}]}

    def parameters(self, chosen):
        with mock.patch.object(presence_shadows, 'automatic', return_value=chosen):
            return entities.checked(self.SCENE)[0]['parameters']

    def test_kept_without_the_preference(self):
        self.assertEqual(self.parameters(False)['presence_shadows'], 1)

    def test_left_out_with_it(self):
        held = self.parameters(True)
        self.assertNotIn('presence_shadows', held)
        self.assertEqual(held['width'], 2.0)


class RealtimeSamplePercent(unittest.TestCase):
    def test_named_alike_wherever_it_is(self):
        self.assertIn("'int', 'Realtime Sample %', ", (KIT / 'python/moonray_modo/scene_settings.py').read_text(encoding='utf-8'))
        self.assertIn('<atom type="Label">Realtime Sample %</atom>', (KIT / 'render_settings.cfg').read_text(encoding='utf-8'))

    def test_in_the_preferences_page(self):
        page = (KIT / 'preferences.cfg').read_text(encoding='utf-8')
        self.assertRegex(page, r'cmd moonray\.render\.xpu2_realtime \?">\s+<atom type="Label">Realtime Sample % \(MoonRay XPU2 only\)')

    def test_in_the_preview_preferences_through_its_command(self):
        dialog = (KIT / 'python/moonray_modo/preferences.py').read_text(encoding='utf-8')
        self.assertIn("form.addRow('Realtime Sample %', self.realtime_share)", dialog)
        self.assertIn("lx.eval('moonray.render.xpu2_realtime %d' % self.realtime_share.value())", dialog)


if __name__ == '__main__':
    unittest.main()
