"""A camera navigated through a viewport is followed even where the drag's first step is looked at late (panel._camera_watch,
_camera_moved). A report: under a heavy scene the preview said "Drag not followed" and went on not following drags until
Follow drags was switched off and on; the viewport looking through the camera was looked for at the drag's first step,
when Modo had already moved it, and none was found."""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/panel.py').read_text(encoding='utf-8')
start = source.index('    def _camera_moved(self):')
end = source.index('    def _live_tick(self):')
CAMERA = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 0, 1.0, 5.0, 1.0]
ELSEWHERE = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, 3.0, 1.0, 5.0, 1.0]
OTHER_VIEW = [1.0, 0, 0, 0, 0, 1.0, 0, 0, 0, 0, 1.0, 0, -9.0, 2.0, 1.0, 1.0]


class Fakes:
    """modo, camera_choice and host as _camera_moved reads them: a render camera standing at CAMERA."""
    def __enter__(self):
        camera = types.SimpleNamespace(id='camera')
        scene = types.SimpleNamespace(renderCamera=camera, item=lambda identity: camera)
        fakes = {'modo': types.SimpleNamespace(Scene=lambda: scene),
                 'moonray_modo': types.ModuleType('moonray_modo'),
                 'moonray_modo.camera_choice': types.SimpleNamespace(current=lambda scene: None),
                 'moonray_modo.host': types.SimpleNamespace(world_matrix=lambda item: list(CAMERA))}
        fakes['moonray_modo'].__path__ = []
        fakes['moonray_modo'].camera_choice = fakes['moonray_modo.camera_choice']
        fakes['moonray_modo'].host = fakes['moonray_modo.host']
        self.kept = {name: sys.modules.get(name) for name in fakes}
        sys.modules.update(fakes)
        return self

    def __exit__(self, *exc):
        for name, module in self.kept.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module


def panel_class():
    namespace = {'__package__': 'moonray_modo', '__name__': 'moonray_modo.panel'}
    exec('class Panel:\n    views = []\n    def _view_matrices(self):\n        return list(self.views)\n' + source[start:end], namespace)
    return namespace['Panel']


class CameraWatch(unittest.TestCase):
    def test_a_late_first_step_still_moves_the_camera(self):
        with Fakes():
            panel = panel_class()()
            # The mouse up: viewport 0 looks through the camera, viewport 1 elsewhere.
            panel.views = [list(CAMERA), list(OTHER_VIEW)]
            panel._camera_watch()
            # The drag's first step looked at only once Modo has moved viewport 0 (the camera item moves on release).
            panel.views = [list(ELSEWHERE), list(OTHER_VIEW)]
            self.assertEqual(panel._camera_moved(), {'camera'})
            self.assertEqual(panel._camera_place, ELSEWHERE)

    def test_without_the_watch_the_late_step_found_nothing(self):
        with Fakes():
            panel = panel_class()()
            panel.views = [list(ELSEWHERE), list(OTHER_VIEW)]
            panel._camera_seen = None
            self.assertEqual(panel._camera_moved(), set())

    def test_watched_twice_a_second_at_most(self):
        with Fakes():
            panel = panel_class()()
            panel.views = [list(CAMERA)]
            panel._camera_watch()
            panel.views = [list(ELSEWHERE)]
            panel._camera_watch()       # within half a second: the baseline stands
            self.assertEqual(panel._camera_seen, ('camera', CAMERA))


if __name__ == '__main__':
    unittest.main()
