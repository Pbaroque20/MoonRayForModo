"""Motion blur by the camera rendered through: the one keyed for the frame in the Camera Sequence, else the MoonRay camera
chosen to render through, else Modo's render camera (host.rendered_camera), as the reading takes it. Its Motion Blur is
what every engine blurs by, realtime too: the preview has no motion blur switch of its own any more (MoonLightIPR's
and XPU2 realtime's were let go in 0.5.5). Asked of the render camera alone, a scene seen through another camera blurred
by one it was not seen through."""
import pathlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

for name in ('modo', 'lx', 'lxifc', 'lxu', 'lxu.utils'):
    sys.modules.setdefault(name, types.ModuleType(name))
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import host  # noqa: E402

KIT = ROOT / 'kit/MoonRayForModo/python/moonray_modo'


def camera(name, blur):
    return SimpleNamespace(id=name, blur=blur)


class RenderedCamera(unittest.TestCase):
    def blurred(self, keyed=None, chosen=''):
        render, moonray, sequenced = camera('render', False), camera('moonray', True), camera('keyed', True)
        items = {'moonray': moonray, 'keyed': sequenced}
        scene = SimpleNamespace(renderCamera=render, fps=24.0, item=lambda identity: items[identity])
        sequence = types.ModuleType('moonray_modo.camera_sequence')
        sequence.keyed = lambda scene, frame: (sequenced, False) if keyed else None
        choice = types.ModuleType('moonray_modo.camera_choice')
        choice.current = lambda scene: chosen
        fake_lx = SimpleNamespace(service=SimpleNamespace(Selection=lambda: SimpleNamespace(GetTime=lambda: 1.0)))
        package = sys.modules['moonray_modo']
        with mock.patch.dict(sys.modules, {'moonray_modo.camera_sequence': sequence, 'moonray_modo.camera_choice': choice}), \
                mock.patch.object(package, 'camera_sequence', sequence, create=True), \
                mock.patch.object(package, 'camera_choice', choice, create=True), \
                mock.patch.object(host, 'lx', fake_lx), \
                mock.patch.object(host, 'channel', lambda item, name, default=None: int(item.blur) if name == 'motionBlur' else default):
            return host.rendered_camera(scene).id, host.camera_motion_blur(scene)

    def test_the_render_camera_where_nothing_else_is_chosen(self):
        self.assertEqual(self.blurred(), ('render', False))

    def test_a_moonray_camera_chosen_to_render_through_is_the_one_asked(self):
        self.assertEqual(self.blurred(chosen='moonray'), ('moonray', True))

    def test_the_camera_sequences_camera_for_the_frame_comes_first(self):
        self.assertEqual(self.blurred(keyed=True, chosen='moonray'), ('keyed', True))


class EveryEngineFollowsIt(unittest.TestCase):
    def read(self, name):
        return (KIT / name).read_text(encoding='utf-8')

    def test_the_preview_has_no_motion_blur_switch_of_its_own(self):
        preferences = self.read('preferences.py')
        keys = preferences[preferences.index('KEYS'):preferences.index('}', preferences.index('KEYS'))]
        self.assertNotIn("'preview_motion'", keys)
        self.assertNotIn("'xpu2_motion'", keys)
        self.assertNotIn("check('preview_motion'", preferences)
        self.assertNotIn("check('xpu2_motion'", preferences)
        # What was stored for them is let go.
        self.assertIn("for gone in ('preview_motion', 'preview_motion_default', 'xpu2_motion'):", preferences)

    def test_moonlightipr_and_xpu2_realtime_blur_by_the_camera(self):
        panel = self.read('panel.py')
        self.assertIn("not self.ipr_mode.isChecked() or not self._motion_wanted():return False", panel)
        body = panel[panel.index('def _moonlightipr_blur'):panel.index('def _moonlightipr_vectors')]
        self.assertIn('return self._motion_wanted()', body)
        self.assertNotIn('preview_motion', panel)
        self.assertNotIn('xpu2_motion', panel)

    def test_exports_and_rhizome_blur_by_the_camera_at_each_frame(self):
        self.assertIn("if held.get('final_motion') or host.camera_motion_blur(scene):", self.read('scene_export.py'))
        self.assertIn("if held.get('final_motion') or host.camera_motion_blur(modo.Scene()):", self.read('rhizome_window.py'))


if __name__ == '__main__':
    unittest.main()
