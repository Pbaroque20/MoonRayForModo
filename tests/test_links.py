"""The Links panel (links.py, links_window.py): meshes linked to .lxo files of their own as Scene Proxies, as Adobe
Illustrator's Links panel lists placed images. Its record and status logic, the files it names, and its wiring into
the MoonRay menu and Modo's saves. The Modo side (proxy.convert, proxy.restore, the geometry write) is checked by
tools/probe_cl_links_flow.py and the GUI probe tools/probe_gui_links.py."""
import os
import pathlib
import sys
import tempfile
import time
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
sys.path.insert(0, str(ROOT / 'tools'))
for _name in ('lx', 'lxu', 'lxifc', 'modo'):
    sys.modules.setdefault(_name, types.ModuleType(_name))
from moonray_modo import links  # noqa: E402


class Record(unittest.TestCase):
    def test_a_record_goes_through_a_tag_and_back(self):
        record = {'file': r'C:\scenes\car_links\Wheel.lxo', 'stamp': [1200, 1795143906626884400], 'print': 'ab12', 'standin': None}
        self.assertEqual(links.read_record(links.record_text(record)), record)

    def test_what_is_not_a_record_is_none(self):
        for text in (None, '', 'not json', '[1, 2]', '{"stamp": [1, 2]}', '{"file": ""}', '{"file": 3}'):
            self.assertIsNone(links.read_record(text), text)


class Status(unittest.TestCase):
    record = {'file': 'Box.lxo', 'stamp': [100, 5], 'print': 'aa'}

    def test_embedded_has_none(self):
        self.assertEqual(links.status(links.EMBEDDED, None, None), links.NONE)

    def test_a_linked_proxy(self):
        self.assertEqual(links.status(links.LINKED, self.record, [100, 5]), links.OK)
        self.assertEqual(links.status(links.LINKED, self.record, [100, 9]), links.CHANGED)
        self.assertEqual(links.status(links.LINKED, self.record, [101, 5]), links.CHANGED)
        self.assertEqual(links.status(links.LINKED, self.record, None), links.MISSING)

    def test_a_proxy_made_outside_the_panel_says_nothing_changed(self):
        self.assertEqual(links.status(links.LINKED, {'file': 'Box.lxo'}, [100, 5]), links.OK)
        self.assertEqual(links.status(links.LINKED, None, [100, 5]), links.OK)

    def test_a_mesh_being_edited(self):
        self.assertEqual(links.status(links.EDITING, self.record, [100, 5], 'aa'), links.OK)
        self.assertEqual(links.status(links.EDITING, self.record, [100, 5], 'bb'), links.EDITED)
        self.assertEqual(links.status(links.EDITING, self.record, [100, 6], 'aa'), links.CHANGED)
        self.assertEqual(links.status(links.EDITING, self.record, [100, 6], 'bb'), links.BOTH)
        self.assertEqual(links.status(links.EDITING, self.record, None, 'aa'), links.MISSING)
        # No fingerprint now (the mesh could not be read) or then: not said to be edited.
        self.assertEqual(links.status(links.EDITING, self.record, [100, 5], None), links.OK)
        self.assertEqual(links.status(links.EDITING, {'file': 'Box.lxo', 'stamp': [100, 5]}, [100, 5], 'bb'), links.OK)

    def test_what_a_save_writes(self):
        self.assertEqual(set(links.NEEDS_WRITE), {links.EDITED, links.BOTH, links.MISSING})
        self.assertNotIn(links.CHANGED, links.NEEDS_WRITE, 'a file changed by another hand is not written over unasked')
        for key in (links.OK, links.EDITED, links.CHANGED, links.BOTH, links.MISSING):
            self.assertTrue(links.STATUS_TEXT[key])


class Files(unittest.TestCase):
    def setUp(self):
        self.held = tempfile.TemporaryDirectory()
        self.folder = pathlib.Path(self.held.name)

    def tearDown(self):
        self.held.cleanup()

    def test_beside_the_scene(self):
        self.assertEqual(links.default_folder(r'C:\scenes\car.lxo'), pathlib.Path(r'C:\scenes\car_links'))
        self.assertIsNone(links.default_folder(''))
        self.assertIsNone(links.default_folder(None))

    def test_a_mesh_name_made_a_file_name(self):
        self.assertEqual(links.file_name(self.folder, 'Wheel').name, 'Wheel.lxo')
        self.assertEqual(links.file_name(self.folder, 'Front: Wheel/Left?').name, 'Front_ Wheel_Left_.lxo')
        self.assertEqual(links.file_name(self.folder, '').name, 'Mesh.lxo')
        self.assertEqual(links.file_name(self.folder, ' .. ').name, 'Mesh.lxo')

    def test_a_file_there_or_taken_is_not_written_over(self):
        (self.folder / 'Wheel.lxo').write_bytes(b'x')
        self.assertEqual(links.file_name(self.folder, 'Wheel').name, 'Wheel (2).lxo')
        taken = [self.folder / 'WHEEL (2).lxo']
        self.assertEqual(links.file_name(self.folder, 'Wheel', taken).name, 'Wheel (3).lxo')

    def test_a_files_stamp(self):
        path = self.folder / 'Box.lxo'
        self.assertIsNone(links.stamp(path))
        self.assertIsNone(links.stamp(self.folder))
        path.write_bytes(b'12345')
        held = links.stamp(path)
        self.assertEqual(held[0], 5)
        os.utime(str(path), ns=(time.time_ns(), held[1] + 10_000_000))
        self.assertNotEqual(links.stamp(path), held)

    def test_spellings_modo_has_not_loaded(self):
        # Modo keeps a proxy's file as first loaded, by its path as written, for the whole session; another spelling of
        # the same file is read anew (tools/probe_cl_links_reload.py).
        path = pathlib.Path(r'C:\scenes\car_links\Wheel.lxo')
        self.assertEqual(links.spelling(path, 0), r'C:\scenes\car_links\Wheel.lxo')
        self.assertEqual(links.spelling(path, 1), r'C:\scenes\car_links\.\Wheel.lxo')
        self.assertEqual(links.spelling(path, 2), r'C:\scenes\car_links\.\.\Wheel.lxo')
        self.assertEqual(links.spelled(path, set()), str(path))
        self.assertEqual(links.spelled(path, {r'c:\scenes\car_links\wheel.lxo'}), r'C:\scenes\car_links\.\Wheel.lxo')
        self.assertEqual(links.spelled(path, {str(path), links.spelling(path, 1)}), links.spelling(path, 2))
        # Every spelling is the same file, and the panel shows its own path.
        for count in range(3):
            self.assertTrue(links.same_file(links.spelling(path, count), path))
            self.assertEqual(os.path.normpath(links.spelling(path, count)), str(path))

    def test_one_file_however_written(self):
        self.assertTrue(links.same_file(r'C:\a\B.lxo', r'c:/a/b.lxo'))
        self.assertFalse(links.same_file(r'C:\a\B.lxo', r'C:\a\C.lxo'))
        self.assertFalse(links.same_file(None, r'C:\a\C.lxo'))


class Wiring(unittest.TestCase):
    def test_the_menu_entry_after_relink_missing_images(self):
        import moonray_menu
        rows = [entry[0] for entry in moonray_menu.MENU if entry]
        self.assertEqual(rows.index('cmd moonray.links'), rows.index('cmd moonray.assets.relink') + 1)
        layout = (KIT / 'layout.cfg').read_text(encoding='utf-8')
        self.assertEqual(layout.count('val="cmd moonray.links"><atom type="Label">Links...</atom>'), 1)
        self.assertIn('key="moonray.links@en_US"', (KIT / 'links.cfg').read_text(encoding='utf-8'))

    def test_the_command_and_the_save_hook_come_with_the_kit(self):
        source = (KIT / 'lxserv/moonray_commands.py').read_text(encoding='utf-8')
        self.assertIn("lx.bless(LinksWindow, 'moonray.links')", source)
        self.assertIn('_links.watch_saves()', source)

    def test_saves_are_heard_after_they_are_done_and_not_inside_its_own_writes(self):
        source = pathlib.Path(links.__file__).read_text(encoding='utf-8')
        self.assertIn('def cmdsysevent_ExecutePost(self, cmd, isSandboxed, isPostCmd):', source)
        self.assertIn("name.startswith('scene.save')", source)
        self.assertIn('QtCore.QTimer.singleShot(0, after_save)', source)
        self.assertIn('if _WRITING[0] or isSandboxed:', source)
        # Its listener is taken out as Modo quits (quit_release), as every listener of the kit's.
        self.assertIn('quit_release.listen(held)', source)

    def test_each_action_is_one_command(self):
        # From a button's click (a Qt event) Modo refused the link record's tag ('bad result'): items are changed only
        # inside a command. moonray.links.act runs each action, one step to undo.
        source = (KIT / 'lxserv/moonray_commands.py').read_text(encoding='utf-8')
        self.assertIn("lx.bless(LinksAct, 'moonray.links.act')", source)
        self.assertIn('lx.symbol.fCMD_MODEL | lx.symbol.fCMD_UNDO', source[source.index('class LinksAct'):])
        window = (KIT / 'python/moonray_modo/links_window.py').read_text(encoding='utf-8')
        self.assertIn('links.run(action, ids, path)', window)
        for direct in ('links.link(', 'links.edit(', 'links.update(', 'links.done(', 'links.relink(', 'links.embed('):
            self.assertNotIn(direct, window)
        self.assertEqual(links.ACTIONS, ('link', 'edit', 'update', 'done', 'relink', 'embed', 'standin', 'saved'))

    def test_an_unknown_action_says_so(self):
        with self.assertRaises(ValueError):
            links.act('rename', '[]')
        self.assertIn('rename', links.LAST['error'])

    def test_a_save_with_nothing_to_write_runs_no_command(self):
        from unittest import mock
        with mock.patch.object(links, 'waiting', return_value=[]), mock.patch.object(links, 'run') as ran:
            self.assertEqual(links.after_save(), [])
        ran.assert_not_called()
        with mock.patch.object(links, 'waiting', return_value=['mesh040']), mock.patch.object(links, 'run', return_value=['mesh040']) as ran:
            heard = []
            links.LISTENERS.append(heard.append)
            try:
                self.assertEqual(links.after_save(), ['mesh040'])
            finally:
                links.LISTENERS.remove(heard.append)
        ran.assert_called_once_with('saved')
        self.assertEqual(heard, [['mesh040']])

    def test_no_scene_is_closed_as_modo_quits(self):
        # Closing the scenes holding proxies as Modo quit did not keep Modo from crashing there in the GUI (closed on
        # Qt's aboutToQuit, or before app.quit), and at Python's exit Modo's commands crashed even a scene with no proxy
        # (tools/probe_cl_links_quit.py): the panel runs no command at quit.
        source = pathlib.Path(links.__file__).read_text(encoding='utf-8')
        self.assertNotIn('aboutToQuit', source)
        self.assertNotIn('quit_release.forget(', source)

    def test_a_link_files_opening_and_closing_is_not_seen_by_the_previews(self):
        # A scene made and another closed told a preview its scene was closed: it cleared its picture and stopped the
        # render begun after a Link (panel._poll). What the previews had noted is put back.
        from unittest import mock
        changes = types.SimpleNamespace(closed=False, created=False, full=False)
        fake = types.ModuleType('moonray_modo.panel')
        fake.live_panels = lambda: [types.SimpleNamespace(changes=changes)]
        with mock.patch.dict(sys.modules, {'moonray_modo.panel': fake}):
            with links._unseen_scenes():
                changes.closed = changes.created = changes.full = True
        self.assertEqual((changes.closed, changes.created, changes.full), (False, False, False))
        # What was noted before stays noted.
        changes.full = True
        with mock.patch.dict(sys.modules, {'moonray_modo.panel': fake}):
            with links._unseen_scenes():
                changes.closed = True
        self.assertEqual((changes.closed, changes.full), (False, True))
        source = pathlib.Path(links.__file__).read_text(encoding='utf-8')
        self.assertEqual(source.count('with _unseen_scenes():'), 2)

    def test_after_save_writes_nothing_while_writing(self):
        links._WRITING[0] = True
        try:
            self.assertEqual(links.after_save(), [])
        finally:
            links._WRITING[0] = False

    def test_the_window_finds_no_qt_object_of_modos(self):
        # Asking Qt for Modo's windows wraps them, and Modo crashed as it quit (quit_release).
        source = (KIT / 'python/moonray_modo/links_window.py').read_text(encoding='utf-8')
        for asked in ('allWidgets', 'topLevelWidgets', 'activeWindow()'):
            self.assertNotIn(asked, source)
        self.assertIn('application.aboutToQuit.connect(closing)', source)


if __name__ == '__main__':
    unittest.main()
