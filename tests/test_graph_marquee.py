"""The graph editor's marquee answers at once: nothing slow runs with the button down. No Modo; tools/probe_gui_marquee.py times it in Modo."""
import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python/moonray_modo'
EDITOR = (ROOT / 'node_editor.py').read_text(encoding='utf-8')
WIDGETS = (ROOT / 'node_widgets.py').read_text(encoding='utf-8')


def method(source, owner, name):
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == owner:
            for held in node.body:
                if isinstance(held, ast.FunctionDef) and held.name == name:
                    return ast.get_source_segment(source, held)
    raise LookupError(name)


class Marquee(unittest.TestCase):
    def test_a_selection_waits_for_the_button(self):
        self.assertIn('self.canvas.selectionChanged.connect(self.selection_changed)', EDITOR)
        self.assertIn('if self.view.holding:self.inspect_waiting=True', method(EDITOR, 'Editor', 'selection_changed'))

    def test_the_canvas_starts_its_own_marquee_and_keeps_no_copy_of_the_graph(self):
        press = method(WIDGETS, 'GraphView', 'mousePressEvent')
        self.assertLess(press.index('self.begin_band(event)'), press.index('self.move_before=copy.deepcopy'))
        self.assertIn('self.holding=True', press)

    def test_the_release_lets_the_list_fill(self):
        release = method(WIDGETS, 'GraphView', 'mouseReleaseEvent')
        self.assertLess(release.index('self.editor.selection_settled()'), release.index('self.end_band()'))

    def test_a_click_that_moved_nothing_is_no_step_to_undo(self):
        self.assertIn('if self.editor.graph!=self.move_before:self.editor.remember(self.move_before)', method(WIDGETS, 'GraphView', 'mouseReleaseEvent'))


class FillingTheList(unittest.TestCase):
    def test_it_stops_after_each_row(self):
        fill = method(EDITOR, 'Editor', 'fill_properties')
        self.assertIn('for identity,key,title,single in rows:\n                yield\n', fill.replace('\r\n', '\n'))
        self.assertTrue(fill.replace('\r\n', '\n').rstrip().endswith('self.busy=False;self.filter_properties()'))

    def test_asked_for_directly_it_is_whole_when_it_returns(self):
        inspect = method(EDITOR, 'Editor', 'inspect')
        self.assertIn('for _ in self.fill_properties():pass', inspect)
        self.assertIn('self.fill_job=None', inspect)

    def test_a_slice_gives_way_to_the_button_and_lets_edits_through_between_slices(self):
        piece = method(EDITOR, 'Editor', 'fill_slice')
        self.assertIn('if self.view.holding:', piece)
        self.assertIn('self.busy=False;self.filter_properties()', piece)


if __name__ == '__main__':
    unittest.main()
