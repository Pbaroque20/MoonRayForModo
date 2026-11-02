"""The compositor's canvas shares the graph editor's view, whose release tells its editor; its sliders; and the bokeh settings' words. No Modo."""
import ast
import re
import sys
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo'
PY = ROOT / 'python/moonray_modo'
sys.path.insert(0, str(PY.parent))
sys.modules.setdefault('modo', types.ModuleType('modo'))
sys.modules.setdefault('lx', types.ModuleType('lx'))
from moonray_modo import compositor


def methods(name, owner):
    for node in ast.parse((PY / name).read_text(encoding='utf-8')).body:
        if isinstance(node, ast.ClassDef) and node.name == owner:
            return {held.name for held in node.body if isinstance(held, ast.FunctionDef)}
    raise LookupError(owner)


class Canvas(unittest.TestCase):
    def test_what_the_view_tells_its_editor_the_compositor_has(self):
        source = (PY / 'node_widgets.py').read_text(encoding='utf-8')
        start = source.index('class GraphView')
        release = source[source.index('def mouseReleaseEvent', start):source.index('def mouseDoubleClickEvent', start)]
        asked = set(re.findall(r'self\.editor\.(\w+)\(', release))
        self.assertIn('selection_settled', asked)
        self.assertEqual(asked - methods('compositor_editor.py', 'Editor'), set())


class Sliders(unittest.TestCase):
    def test_each_is_on_a_number_of_that_node_and_within_its_limits(self):
        for (kind, key), (low, high) in compositor.SLIDERS.items():
            spec = compositor.NODES[kind]['parameters'][key]
            self.assertEqual(spec[0], 'number')
            self.assertGreaterEqual(low, spec[2])
            self.assertLessEqual(high, spec[3])

    def test_a_number_without_one_stays_a_number(self):
        self.assertIsNone(compositor.slider_range('grade', 'exposure', ('number', 0.0, -10.0, 10.0)))

    def test_the_form_makes_the_row(self):
        source = (PY / 'compositor_editor.py').read_text(encoding='utf-8')
        self.assertIn('field = SliderRow(field, span,', source)
        self.assertIn('import SliderRow', source)


class Bokeh(unittest.TestCase):
    def test_the_two_weights_say_they_do_nothing(self):
        forms = (ROOT / 'entities.cfg').read_text(encoding='utf-8')
        self.assertIn('bokeh weight location (no effect)', forms)
        self.assertIn('bokeh weight strength (no effect)', forms)
        self.assertNotIn('>bokeh weight location<', forms)

    def test_edge_weighting_is_said_where_it_is_moved_from_even(self):
        source = (PY / 'host.py').read_text(encoding='utf-8')
        self.assertIn("abs(float(channel(camera, 'irisBias', .5)) - .5) > 1e-4", source)


if __name__ == '__main__':
    unittest.main()
