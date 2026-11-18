"""LXO to RDL: the scenes found among what is given, where each is written, what modo_cl is told and the export's report
read back (lxo_convert.py), the export script's words, the menu entry and the command-line converter in bin. No Modo."""
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = ROOT / 'kit/MoonRayForModo'
sys.path.insert(0, str(KIT / 'python'))
sys.path.insert(0, str(ROOT / 'tools'))


def load():
    """lxo_convert with a stand-in for Qt, taken away again at once so that other tests still find Qt missing."""
    try:
        from moonray_modo import lxo_convert
        return lxo_convert
    except ImportError:
        pass
    qt = types.ModuleType('PySide2')

    class QObject:
        def __init__(self, parent=None):
            pass
    qt.QtCore = types.SimpleNamespace(QObject=QObject, Signal=lambda *a: None, QSettings=None, QProcess=None)
    qt.QtWidgets = types.SimpleNamespace(QDialog=object)
    held = {name: sys.modules.get(name) for name in ('PySide2', 'moonray_modo.lxo_convert', 'moonray_modo.scene_export')}
    sys.modules['PySide2'] = qt
    try:
        from moonray_modo import lxo_convert
        return lxo_convert
    finally:
        for name, module in held.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        for name in ('lxo_convert', 'scene_export'):
            vars(sys.modules['moonray_modo']).pop(name, None)


convert = load()


class Scenes(unittest.TestCase):
    def test_files_and_folders_each_scene_once(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'shots/b').mkdir(parents=True)
            for name in ('a.lxo', 'shots/b/c.LXO', 'shots/notes.txt', 'shots/b/a.lxo'):
                (root / name).write_text('x')
            found = convert.lxo_files([root / 'a.lxo', root, root / 'shots/notes.txt'])
            self.assertEqual([p.relative_to(root.resolve()).as_posix() for p in found], ['a.lxo', 'shots/b/a.lxo', 'shots/b/c.LXO'])

    def test_beside_each_scene(self):
        placed = convert.targets([Path('C:/a/shot.lxo'), Path('C:/b/shot.lxo')], 'rdlb')
        self.assertEqual([p.as_posix() for p in placed], ['C:/a/shot.rdlb', 'C:/b/shot.rdlb'])

    def test_one_folder_keeps_two_of_a_name_apart(self):
        placed = convert.targets([Path('C:/a/shot.lxo'), Path('C:/b/Shot.lxo'), Path('C:/c/other.lxo')], 'split', 'D:/out')
        self.assertEqual([p.as_posix() for p in placed], ['D:/out/shot.rdla', 'D:/out/Shot_2.rdla', 'D:/out/other.rdla'])


class Commands(unittest.TestCase):
    def test_what_modo_cl_is_told(self):
        text = convert.command_text(Path('C:/My Scenes/shot.lxo'), Path('D:/out/shot.rdlb'), 'rdlb', frames=True, outputs=False,
                                    collect=True, report=Path('C:/Temp/0.report.txt'))
        first, second = text.splitlines()
        self.assertTrue(first.startswith('@{%s} ' % convert.script()))
        self.assertIn('"%s" "%s"' % (Path('C:/My Scenes/shot.lxo'), Path('D:/out/shot.rdlb')), first)
        self.assertTrue(first.endswith('format=rdlb outputs=0 collect=1 frames "report=%s"' % Path('C:/Temp/0.report.txt')))
        self.assertEqual(second, 'app.quit')

    def test_the_report_read_back(self):
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / 'r.txt'
            report.write_text('wrote\tD:/out/shot.rdla\nwrote\tD:/out/shot.rdlb\nnotice\tA light is left out\nerror\tValueError: no\n', encoding='utf-8')
            self.assertEqual(convert.read_report(report), (['D:/out/shot.rdla', 'D:/out/shot.rdlb'], ['A light is left out'], ['ValueError: no']))
            self.assertEqual(convert.read_report(Path(folder) / 'none.txt'), ([], [], []))

    def test_the_export_script_takes_the_words(self):
        script = (KIT / 'scripts/export_moonray.py').read_text(encoding='utf-8')
        for word in ("named.get('format'", "'frames' in", "named.get('outputs', '1') != '0'", "named.get('collect', '0') == '1'",
                     "named.get('report')", "lx.eval('!scene.open {%s}' % args[0])"):
            self.assertIn(word, script)
        # A report's path keeps its own case.
        self.assertIn("word.split('=', 1)[0].lower(): word.split('=', 1)[1]", script)


class Wiring(unittest.TestCase):
    def test_the_menu_entry(self):
        layout = (KIT / 'layout.cfg').read_text(encoding='utf-8')
        self.assertIn('val="cmd moonray.lxo.convert"><atom type="Label">Convert LXO to RDL...</atom>', layout)
        self.assertIn("lx.bless(ConvertLxo, 'moonray.lxo.convert')", (KIT / 'lxserv/moonray_commands.py').read_text(encoding='utf-8'))

    def test_it_takes_the_place_of_export_as_moonray_scene(self):
        import moonray_menu
        layout = (KIT / 'layout.cfg').read_text(encoding='utf-8')
        self.assertNotIn('cmd moonray.scene.export', layout)
        # An installed menu is written again from the menu's list (moonray_menu.tidy): the converter where the export was.
        rows = [entry[0] for entry in moonray_menu.MENU if entry]
        self.assertIn('cmd moonray.lxo.convert', rows)
        self.assertNotIn('cmd moonray.scene.export', rows)
        self.assertEqual(rows.index('cmd moonray.lxo.convert'), rows.index('cmd moonray.material.importMaterialX') + 1)
        # The preview's Options, and the old command for a keymap or a script, open the converter.
        self.assertIn("menu.addAction('Convert LXO to RDL...',self.export_moonray_scene)", (KIT / 'python/moonray_modo/panel.py').read_text(encoding='utf-8'))
        self.assertIn('from moonray_modo.lxo_convert_window import show', (KIT / 'lxserv/moonray_scene_export.py').read_text(encoding='utf-8'))
        self.assertIn('def add_open_scene(self):', (KIT / 'python/moonray_modo/lxo_convert_window.py').read_text(encoding='utf-8'))

    def test_an_installed_menu_gains_it_once(self):
        import moonray_menu
        row = '      <list type="Control" val="cmd moonray.scene.export"><atom type="Label">Export as MoonRay Scene...</atom></list>'
        text = '<hash>\r\n' + row + '\r\n</hash>'
        added = moonray_menu.lxo_convert_entry(text)
        self.assertEqual(added.count('cmd moonray.lxo.convert'), 1)
        self.assertEqual(moonray_menu.lxo_convert_entry(added), added)
        self.assertIn('moonray_menu.lxo_convert_entry(', (ROOT / 'tools/install_moonlightipr.py').read_text(encoding='utf-8'))

    def test_the_command_line_converter_ships_in_bin(self):
        self.assertIn("kit[prefix+'bin/lxo2rdl.exe']=lxo2rdl", (ROOT / 'tools/package_development_release.py').read_text(encoding='utf-8'))
        self.assertIn("'bin/lxo2rdl.exe'", (ROOT / 'tools/check_release_package.py').read_text(encoding='utf-8'))
        source = (ROOT / 'native-port/lxo2rdl.cpp').read_text(encoding='utf-8')
        # It finds the export script from its own place in the kit, and tells the script where to report.
        self.assertIn('self().parent_path().parent_path() / L"scripts" / L"export_moonray.py"', source)
        self.assertIn('L" \\"report=" + report.wstring()', source)


if __name__ == '__main__':
    unittest.main()
