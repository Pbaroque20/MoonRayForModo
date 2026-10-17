"""The MoonRay Terminal's record: commands as typed, what programs print split into lines, how they end, and programs the
plugin starts with Python's subprocess seen by the audit hook; and its entry in the MoonRay menu."""
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
sys.path.insert(0, str(ROOT / 'tools'))
from moonray_modo import terminal
import moonray_menu


def kinds(after):
    return [(kind, source, text) for _, _, kind, source, text in terminal.entries(after)]


def last():
    held = terminal.entries()
    return held[-1][0] if held else 0


class Record(unittest.TestCase):
    def test_a_command_its_lines_and_its_end(self):
        start = last()
        ident = terminal.command(r'C:\Program Files\MoonRay\moonray.exe', ['-in', 'my scene.rdla', '-threads', '8'], 'MoonRay')
        terminal.output(ident, 'Loading scene\r\nRender progr')
        terminal.output(ident, 'ess 50%\nhalf')
        terminal.ended(ident, 0)
        got = kinds(start)
        self.assertEqual(got[0], ('command', 'MoonRay', '"C:\\Program Files\\MoonRay\\moonray.exe" -in "my scene.rdla" -threads 8'))
        self.assertEqual([t for k, s, t in got if k == 'out'], ['Loading scene', 'Render progress 50%', 'half'])
        self.assertEqual(got[-1][0], 'end')
        self.assertTrue(got[-1][2].startswith('exited 0 after'))

    def test_a_failure_and_a_crash(self):
        start = last()
        terminal.ended(terminal.command('a.exe', [], 'A'), 3)
        terminal.ended(terminal.command('b.exe', [], 'B'), -1073741819, crashed=True)
        ends = [(k, t.split(' after')[0]) for k, s, t in kinds(start) if k in ('end', 'fail')]
        self.assertEqual(ends, [('fail', 'exited 3'), ('fail', 'crashed (0xC0000005)')])

    def test_a_program_the_plugin_stops_is_stopped_not_crashed(self):
        start = last()
        terminal.ended(terminal.command('moonray.exe', [], 'MoonRay session'), terminal.KILLED, crashed=True, stopped=True)
        got = kinds(start)[-1]
        self.assertEqual(got[0], 'stop')
        self.assertTrue(got[2].startswith('stopped after'))

    def test_each_status_the_preview_window_shows_is_noted_once(self):
        class Label:
            def __init__(self):
                self.words = 'Ready'

            def text(self):
                return self.words

            def setText(self, words):
                self.words = words
        label = Label()
        start = last()
        terminal.follow_status(label)
        for words in ('Rendering \n· CPU', 'Rendering · CPU', 'Done'):
            label.setText(words)
        self.assertEqual(label.text(), 'Done')
        self.assertEqual(kinds(start), [('status', 'Preview', 'Ready'), ('status', 'Preview', 'Rendering · CPU'), ('status', 'Preview', 'Done')])

    def test_a_session_kept_running_does_not_make_it_busy(self):
        session = terminal.command('moonray.exe', ['-session'], 'MoonRay session')
        terminal._resident.add(session)
        self.assertFalse(terminal.busy())
        render = terminal.command('denoise.exe', [], 'Denoiser')
        self.assertTrue(terminal.busy())
        terminal.ended(render, 0)
        terminal.ended(session, 0)
        self.assertFalse(terminal.busy())
        terminal.working(True)
        self.assertTrue(terminal.busy())
        terminal.working(False)
        self.assertFalse(terminal.busy())

    def test_the_record_is_kept_to_its_limit(self):
        self.assertEqual(terminal._entries.maxlen, terminal.LIMIT)


class Subprocesses(unittest.TestCase):
    def test_the_plugins_own_subprocess_is_recorded_with_its_exit(self):
        terminal.install()
        start = last()
        # Code that runs from the kit's own folder, as the plugin's modules do.
        source = 'import subprocess, sys\nsubprocess.run([sys.executable, "-c", "raise SystemExit(4)"])\n'
        exec(compile(source, str(ROOT / 'kit/MoonRayForModo/python/moonray_modo/fake_caller.py'), 'exec'), {})
        got = kinds(start)
        commands = [(s, t) for k, s, t in got if k == 'command']
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][0], 'fake_caller')
        self.assertIn('raise SystemExit(4)', commands[0][1])
        # As typed: quoted once, not twice.
        self.assertFalse(commands[0][1].startswith('"\\"'))
        self.assertTrue(any(k == 'fail' and t.startswith('exited 4') for k, s, t in got))

    def test_a_subprocess_from_elsewhere_is_not(self):
        terminal.install()
        start = last()
        subprocess.run([sys.executable, '-c', 'pass'])
        self.assertEqual([k for k, s, t in kinds(start) if k == 'command'], [])


class Menu(unittest.TestCase):
    def test_the_kit_menu_has_the_terminal_after_the_render_log(self):
        text = (ROOT / 'kit/MoonRayForModo/layout.cfg').read_text(encoding='utf-8')
        self.assertEqual(text.count('cmd moonray.terminal'), 1)
        self.assertLess(text.index('cmd moonray.page log'), text.index('cmd moonray.terminal'))

    def test_an_installed_menu_gains_the_entry_once(self):
        old = ('<list type="Control" val="cmd moonray.page log"><atom type="Label">Render Log</atom></list>\r\n'
               '<list type="Control" val="cmd moonray.about"></list>\r\n')
        new = moonray_menu.terminal_entry(old)
        self.assertEqual(new.count('cmd moonray.terminal'), 1)
        self.assertLess(new.index('Render Log'), new.index('>Terminal<'))
        self.assertEqual(moonray_menu.terminal_entry(new), new)

    def test_the_command_is_registered(self):
        text = (ROOT / 'kit/MoonRayForModo/lxserv/moonray_commands.py').read_text(encoding='utf-8')
        self.assertIn("lx.bless(MoonRayTerminal,'moonray.terminal')", text)


if __name__ == '__main__':
    unittest.main()
