"""A graph editor open on a material that is then deleted closes, instead of crashing Modo.

A DWA material made, its MoonShine network open, the material deleted: Modo crashed. The editor watched for its scene
closing (scene_watch) but not for its own material going, so its preview and timers went on reading a deleted item.
scene_watch now tells ITEM_LISTENERS of each item about to be deleted, and the editor lets go of its material (stops
the preview, writes nothing, closes; docked, the dock shows its placeholder) when that item, or a group holding it, is
deleted. tools/probe_gui_graph_material_deleted.py checks it in a test Modo."""
import pathlib
import sys
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'kit/MoonRayForModo/python/moonray_modo'
sys.path.insert(0, str(PACKAGE.parent))


class _Item:
    def __init__(self, ident, scene):
        self.ident, self.scene = ident, scene

    def Ident(self):
        return self.ident

    def Context(self):
        return self.scene


class _Scene:
    def __init__(self, address):
        self.address = address

    def __peekobj__(self):
        return self.address


def _stub_lx():
    lx = types.ModuleType('lx')
    lx.object = types.SimpleNamespace(Item=lambda item: item, Scene=lambda scene: scene)
    lxifc = types.ModuleType('lxifc')
    lxifc.SceneItemListener = object
    return lx, lxifc


class ItemRemovals(unittest.TestCase):
    def setUp(self):
        self.saved = {name: sys.modules.get(name) for name in ('lx', 'lxifc', 'moonray_modo.scene_watch')}
        sys.modules['lx'], sys.modules['lxifc'] = _stub_lx()
        sys.modules.pop('moonray_modo.scene_watch', None)
        from moonray_modo import scene_watch
        self.watch = scene_watch
        scene_watch._held.update(listener=object(), com=object())     # no Modo to add a listener to

    def tearDown(self):
        for name, module in self.saved.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module

    def test_told_ident_and_scene_before_it_goes(self):
        heard = []
        listener = lambda ident, key: heard.append((ident, key))
        self.watch.watch_items(listener)
        self.watch._Listener().sil_ItemRemove(_Item('material019', _Scene(7)))
        self.assertEqual(heard, [('material019', 7)])
        self.watch.unwatch_items(listener)
        self.watch._Listener().sil_ItemRemove(_Item('material020', _Scene(7)))
        self.assertEqual(len(heard), 1)

    def test_a_failing_listener_does_not_stop_the_others(self):
        heard = []
        def broken(ident, key):
            raise RuntimeError('gone')
        self.watch.watch_items(broken)
        self.watch.watch_items(lambda ident, key: heard.append(ident))
        self.watch._Listener().sil_ItemRemove(_Item('mask003', _Scene(1)))
        self.assertEqual(heard, ['mask003'])

    def test_scene_listeners_kept_apart(self):
        closed = []
        self.watch.watch(closed.append)
        self.watch._Listener().sil_ItemRemove(_Item('material001', _Scene(1)))
        self.assertEqual(closed, [])
        self.watch._Listener().sil_SceneDestroy(_Scene(1))
        self.assertEqual(closed, [1])


class EditorLetsGo(unittest.TestCase):
    """node_editor needs PySide2 (Modo's Python): its wiring checked in the source."""
    source = (PACKAGE / 'node_editor.py').read_text(encoding='utf-8')

    def test_watches_its_material(self):
        self.assertIn('scene_watch.watch_items(self.item_removed)', self.source)
        self.assertIn('scene_watch.unwatch_items(self.item_removed)', self.source)

    def test_material_or_group_lets_go(self):
        start = self.source.index('def item_removed(self,ident,key):')
        body = self.source[start:self.source.index('def let_go(self):', start)]
        self.assertIn('ident==self.item_ident', body)
        self.assertIn('parent.id==ident', body)
        self.assertIn('self.let_go()', body)

    def test_parent_never_found_among_modos_windows(self):
        # Looking through Modo's windows wraps them, and Modo crashed on quitting after any graph editor had opened with
        # Modo in the background (tools/probe_gui_quit_after_editor.py).
        start = self.source.index('def _modo_window():')
        body = self.source[start:self.source.index('def bring_forward(', start)]
        code = body[body.index('"""', body.index('"""') + 3) + 3:]
        self.assertNotIn('topLevelWidgets', code)
        self.assertNotIn('allWidgets', code)
        self.assertIn('activeWindow()', code)

    def test_nothing_written_after(self):
        start = self.source.index('def save(self,close=True):')
        self.assertIn("if getattr(self,'scene_gone',False):return", self.source[start:start + 120])
        start = self.source.index('def let_go(self):')
        body = self.source[start:start + 700]
        self.assertIn('self.material_preview.shutdown()', body)
        self.assertIn('self.done(0)', body)


if __name__ == '__main__':
    unittest.main()
