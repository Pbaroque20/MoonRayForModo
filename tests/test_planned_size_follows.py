"""The size said beside the picture follows the scene while nothing renders (panel._planned_follows): a scene opened is
said at once, and a resolution or camera changed is said again; a render, realtime, a draft or an output render keep
what they say. A report: a scene loaded kept the size of the one before, or the window's first."""
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/panel.py').read_text(encoding='utf-8')
start = source.index('    def _planned_follows(self,opened):')
end = source.index('    def _show_planned(self):')
namespace = {}
exec('class Panel:\n' + source[start:end], namespace)
follows = namespace['Panel']._planned_follows


class Window:
    def __init__(self, size=(640, 360), said=None):
        self.disposed = self._rendering = self._following = False
        self.draft = types.SimpleNamespace(isChecked=lambda: False)
        self.size, self._planned_said, self.shown = size, said, 0

    def _output_busy(self):
        return False

    def _planned_size(self):
        return self.size

    def _show_planned(self):
        self.shown += 1
        self._planned_said = self.size


class Follows(unittest.TestCase):
    def test_a_scene_opened_is_said_at_once_even_at_the_same_size(self):
        w = Window(said=(640, 360))
        follows(w, True)
        self.assertEqual(w.shown, 1)

    def test_a_new_size_is_said_and_the_same_one_is_not_said_again(self):
        w = Window(said=(640, 360))
        follows(w, False)
        self.assertEqual(w.shown, 0)
        w.size, w._planned_looked = (1200, 300), 0.0
        follows(w, False)
        self.assertEqual(w.shown, 1)

    def test_nothing_is_said_over_a_render(self):
        for state in ('_rendering', '_following'):
            w = Window(said=(1, 1))
            setattr(w, state, True)
            follows(w, True)
            self.assertEqual(w.shown, 0, state)
        w = Window(said=(1, 1))
        w.draft = types.SimpleNamespace(isChecked=lambda: True)
        follows(w, True)
        self.assertEqual(w.shown, 0)

    def test_a_scene_opened_while_a_render_stops_is_said_once_it_has(self):
        w = Window(said=(640, 360))
        w._rendering = True
        follows(w, True)
        w._rendering, w._planned_looked = False, 0.0
        follows(w, False)
        self.assertEqual(w.shown, 1)


if __name__ == '__main__':
    unittest.main()
