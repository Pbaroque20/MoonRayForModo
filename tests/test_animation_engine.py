"""Render Animation's engine: MoonRay (XPU), MoonRay (XPU2) or MoonLightIPR. MoonRay (XPU2) is XPU2's whatever renders
the preview and whatever the execution mode, where the kit holds XPU2; MoonRay (XPU) never is. render.xpu2_output is run
as written, with what it asks of the kit stood in for. No Modo."""
import ast
import types
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python/moonray_modo'


def rule(preview_xpu2=True, available=True, slow=None):
    """render.xpu2_output, with the preview's choice (native.xpu2), the kit's XPU2 (native.xpu2_available) and what
    MoonRay draws rightly only in its scalar mode (scalar_only) as given."""
    tree = ast.parse((KIT / 'render.py').read_text(encoding='utf-8'))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'xpu2_output')
    namespace = {'native': types.SimpleNamespace(xpu2=lambda: preview_xpu2 and available, xpu2_available=lambda: available),
                 'scalar_only': lambda snapshot: slow, 'COOKIE': 'cookie', 'VDB_ITEM': 'vdb'}
    exec(compile(ast.Module(body=[function], type_ignores=[]), 'render.py', 'exec'), namespace)
    return namespace['xpu2_output']


class Routing(unittest.TestCase):
    def test_xpu2_where_it_renders_the_preview(self):
        decide = rule(preview_xpu2=True)
        self.assertTrue(decide({'_xpu2_output': True}))
        self.assertTrue(decide({'_xpu2_output': 'chosen'}))

    def test_moonray_xpu_asks_for_none(self):
        # MoonRay (XPU): the sequence sets no _xpu2_output at all (animation.Sequence).
        self.assertFalse(rule(preview_xpu2=True)({}))

    def test_xpu2_by_name_where_moonray_xpu_renders_the_preview(self):
        decide = rule(preview_xpu2=False)
        self.assertFalse(decide({'_xpu2_output': True}))
        self.assertTrue(decide({'_xpu2_output': 'chosen'}))

    def test_not_without_xpu2_in_the_kit(self):
        self.assertFalse(rule(available=False)({'_xpu2_output': 'chosen'}))

    def test_by_name_whatever_the_execution_mode(self):
        decide = rule()
        self.assertFalse(decide({'_xpu2_output': True, 'execution_mode': 'vector'}))
        self.assertTrue(decide({'_xpu2_output': 'chosen', 'execution_mode': 'vector'}))

    def test_what_only_moonray_writes_stays_moonrays(self):
        self.assertFalse(rule()({'_xpu2_output': 'chosen', 'recovery': {'enabled': True}}))
        self.assertFalse(rule(slow='glowing VDB')({'_xpu2_output': 'chosen'}))
        self.assertTrue(rule(slow='cookie')({'_xpu2_output': 'chosen'}))


class Wiring(unittest.TestCase):
    def read(self, name):
        return (KIT / name).read_text(encoding='utf-8')

    def test_the_window_offers_three_engines(self):
        window = self.read('output_dialog.py')
        for item in ("addItem('MoonRay (XPU)','xpu')", "addItem('MoonRay (XPU2)','xpu2')", "addItem('MoonLightIPR','moonlightipr')"):
            self.assertIn(item, window)
        # What was kept before there were two: the one the preview renders with.
        self.assertIn("if held=='moonray':held='xpu2' if native.xpu2() else 'xpu'", window)

    def test_the_sequence_asks_by_its_engine(self):
        self.assertIn("engine=dialog.engine.currentData()", self.read('panel_tools.py'))
        self.assertIn("if engine!='xpu':snapshot['_xpu2_output']='chosen' if engine=='xpu2' else True", self.read('animation.py'))

    def test_the_session_follows_the_name_and_starts_again_only_for_another_renderer(self):
        session = self.read('persistent.py')
        self.assertIn("if getattr(session,'output_xpu2',False):return native.xpu2_available()", session)
        self.assertEqual(session.count('native.source_switches()+(xpu2_chosen(self),)'), 2)
        render = self.read('render.py')
        self.assertIn("self.session.output_xpu2=named", render)
        self.assertIn("if named and mode not in ('xpu','auto'):mode='auto'", render)


if __name__ == '__main__':
    unittest.main()
