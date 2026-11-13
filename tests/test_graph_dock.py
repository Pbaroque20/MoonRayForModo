"""The MoonShine graph editor docked in a Modo viewport (graph_dock, lxserv MoonRayGraphView): the layout gains its
viewport and the MoonRay menu's Use Graph Editor in Current Viewport, once (moonray_menu.graph_dock_entry, which the
installer runs on the installed layout); the editor takes a host to sit in as a widget."""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import moonray_menu  # noqa: E402

KIT = ROOT / 'kit/MoonRayForModo'


class GraphDock(unittest.TestCase):
    def test_the_kit_layout_has_the_view_and_the_menu_entry_once(self):
        text = (KIT / 'layout.cfg').read_text(encoding='utf-8')
        self.assertEqual(text.count('key="base.MoonRayGraphViewport"'), 1)
        self.assertEqual(text.count('val="cmd moonray.graph.dock"'), 1)
        self.assertIn('<atom type="Server">MoonRayGraphView</atom>', text)
        self.assertEqual(moonray_menu.graph_dock_entry(text), text)

    def test_an_older_layout_gains_them_after_moonrays_own(self):
        text = (KIT / 'layout.cfg').read_text(encoding='utf-8')
        older = text.replace(moonray_menu.GRAPH_ROW, '')
        start = older.index('<hash type="customview" key="base.MoonRayGraphViewport"')
        older = older[:start] + older[older.index('</hash>', start) + len('</hash>'):]
        made = moonray_menu.graph_dock_entry(older)
        self.assertEqual(made.count('key="base.MoonRayGraphViewport"'), 1)
        self.assertLess(made.index('cmd moonray.dock"'), made.index('cmd moonray.graph.dock"'))

    def test_the_installer_and_the_server_are_wired(self):
        self.assertIn('moonray_menu.graph_dock_entry(', (ROOT / 'tools/install_moonlightipr.py').read_text(encoding='utf-8'))
        commands = (KIT / 'lxserv/moonray_commands.py').read_text(encoding='utf-8')
        self.assertIn("lx.bless(MoonRayGraphView, 'MoonRayGraphView'", commands)
        self.assertIn("lx.bless(DockGraph, 'moonray.graph.dock')", commands)
        editor = (KIT / 'python/moonray_modo/node_editor.py').read_text(encoding='utf-8')
        self.assertIn('def __init__(self,item,materialx_override=False,host=None):', editor)


if __name__ == '__main__':
    unittest.main()
