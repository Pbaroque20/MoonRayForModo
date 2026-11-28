"""UDIM sets in the graph editor and the material form, and a graph editor that cannot open.

A tester's UDIM set showed a magenta picture on its Image node (the thumbnail read tile 1001, which the set did not
have), and nothing said it was a set. The picture is now the first tile found, marked UDIM SET with the count; a set
with no tile found is the missing colour with words saying so; the form and the editor's file field name the tiles.
The same tester's Open Graph Editor did nothing on such a material, and choosing it in the editor's list closed the
window: a failure to make the editor is now said (message box, Event Log, diagnostics) and the window stays."""
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGE = ROOT / 'kit/MoonRayForModo/python/moonray_modo'
sys.path.insert(0, str(PACKAGE.parent))
from moonray_modo import graph_images


class UdimWords(unittest.TestCase):
    def setUp(self):
        self.held = tempfile.TemporaryDirectory()
        self.folder = pathlib.Path(self.held.name)
        for number in (1002, 1003, 1034):
            (self.folder / ('body.%d.exr' % number)).write_bytes(b'')
        (self.folder / 'other.1001.exr').write_bytes(b'')

    def tearDown(self):
        self.held.cleanup()

    def test_a_set_says_its_tiles(self):
        pattern = (self.folder / 'body.<UDIM>.exr').as_posix()
        self.assertEqual(graph_images.udim_tiles(pattern), [1002, 1003, 1034])
        self.assertEqual(graph_images.udim_words(pattern), 'UDIM, 3 tiles (1002-1034)')
        self.assertEqual(graph_images.label(('image', pattern)), 'body.<UDIM>.exr - UDIM, 3 tiles (1002-1034)')

    def test_a_set_with_no_tiles(self):
        pattern = (self.folder / 'missing.<UDIM>.exr').as_posix()
        self.assertEqual(graph_images.udim_tiles(pattern), [])
        self.assertEqual(graph_images.udim_words(pattern), 'UDIM, no tiles found')
        self.assertEqual(graph_images.udim_words('C:/nowhere/at/all/x.<UDIM>.exr'), 'UDIM, no tiles found')

    def test_a_single_image_is_named_alone(self):
        single = (self.folder / 'other.1001.exr').as_posix()
        self.assertIsNone(graph_images.udim_words(single))
        self.assertEqual(graph_images.label(('image', single)), 'other.1001.exr')
        self.assertEqual(graph_images.label(None), '(none)')


class Thumbnails(unittest.TestCase):
    """node_previews needs PySide2 (Modo's Python; tools/probe_gui_graph_udim.py shows it in a test Modo)."""
    source = (PACKAGE / 'node_previews.py').read_text(encoding='utf-8')

    def test_first_tile_found_not_1001(self):
        self.assertNotIn("replace('<UDIM>', '1001')", self.source)
        self.assertIn('first = min(tiles)', self.source)

    def test_set_marked_and_missing_set_said(self):
        self.assertIn("'UDIM SET ", self.source)
        self.assertIn('draw_badge(image, self.badge)', self.source)
        self.assertIn("NO_TILES = 'No UDIM tiles found'", self.source)
        self.assertIn('item.show_preview(None, missing=NO_TILES)', self.source)
        # A set's picture is kept apart from its tile's own.
        self.assertIn('named += (badge,)', self.source)


class EditorFailures(unittest.TestCase):
    editor = (PACKAGE / 'node_editor.py').read_text(encoding='utf-8')

    def test_failure_is_said_not_silent(self):
        self.assertIn('raise OpenFailed(open_failed(item,exc)) from exc', self.editor)
        for said in ('QtWidgets.QMessageBox.Warning', "lx.out('MoonRay: '+line)", 'record(said'):
            self.assertIn(said, self.editor)

    def test_a_part_made_editor_lets_go(self):
        self.assertIn('try:self.build(item,materialx_override)', self.editor)
        self.assertIn('def build(self,item,materialx_override):', self.editor)

    def test_switching_keeps_the_window_when_the_other_fails(self):
        switch = self.editor[self.editor.index('    def switch_material'):self.editor.index('    def keyPressEvent')]
        self.assertIn('except OpenFailed', switch)
        self.assertNotIn('QtCore.QTimer.singleShot(0,self.reject)', switch)
        self.assertIn('editor.isVisible()', switch)

    def test_parent_is_never_a_popup_or_another_editor(self):
        self.assertIn('super().__init__(_modo_window())', self.editor)
        self.assertIn('QtCore.Qt.Popup', self.editor)

    def test_command_and_dock_do_not_fail_twice(self):
        command = (ROOT / 'kit/MoonRayForModo/lxserv/moonray_material_properties.py').read_text(encoding='utf-8')
        self.assertIn('except OpenFailed:pass', command)
        dock = (PACKAGE / 'graph_dock.py').read_text(encoding='utf-8')
        self.assertIn('open_failed(item, exc, self)', dock)
        self.assertIn('self.followed = item.id', dock)


if __name__ == '__main__':
    unittest.main()
