"""The Render button reads Pause, not Stop, while XPU2 renders the preview under Safe Denoising: a stop then saves the
render where it stands, and Continue takes it up from there. MoonRay's own renders, MoonLightIPR's, realtime, a draft,
a render to files, and Safe Denoising off keep Render, Stop and Continue. The button keeps one width whatever it says.

panel.py needs Qt and Modo to import: its rule is read from the file and run here on its own."""
import ast
import itertools
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python/moonray_modo/panel.py'


def rule():
    """START_WORDS, pauses and start_word, as panel.py has them."""
    tree = ast.parse(PANEL.read_text(encoding='utf-8'))
    wanted = [node for node in tree.body
              if (isinstance(node, ast.FunctionDef) and node.name in ('pauses', 'start_word'))
              or (isinstance(node, ast.Assign) and any(getattr(t, 'id', '') == 'START_WORDS' for t in node.targets))]
    space = {}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), str(PANEL), 'exec'), space)
    return space


class PauseRule(unittest.TestCase):
    def setUp(self):
        space = rule()
        self.pauses, self.word, self.words = space['pauses'], space['start_word'], space['START_WORDS']

    def test_xpu2_under_safe_denoising_pauses(self):
        self.assertTrue(self.pauses('moonray', True, True))
        self.assertEqual(self.word(True, False, True), 'Pause')
        # Paused, it is continued.
        self.assertEqual(self.word(False, True, True), 'Continue')
        # Nothing kept to continue: Render.
        self.assertEqual(self.word(False, False, True), 'Render')

    def test_everything_else_stops(self):
        self.assertFalse(self.pauses('moonray', False, True))       # MoonRay renders (no XPU2, or Vector/Scalar mode)
        self.assertFalse(self.pauses('moonlightipr', True, True))   # MoonLightIPR
        self.assertFalse(self.pauses('moonray', True, False))       # Safe Denoising off
        self.assertFalse(self.pauses('moonray', True, True, realtime=True))
        self.assertFalse(self.pauses('moonray', True, True, draft=True))
        self.assertFalse(self.pauses('moonray', True, True, output=True))
        self.assertEqual(self.word(True, False, False), 'Stop')
        self.assertEqual(self.word(False, True, False), 'Continue')
        self.assertEqual(self.word(False, False, False), 'Render')

    def test_the_button_is_as_wide_as_every_word_it_says(self):
        said = {self.word(active, again, pausing) for active, again, pausing in itertools.product((False, True), repeat=3)}
        self.assertEqual(said, {'Render', 'Stop', 'Pause', 'Continue'})
        self.assertLessEqual(said | {'Stopping', 'Pausing'}, set(self.words))


class PauseWiring(unittest.TestCase):
    def setUp(self):
        self.text = PANEL.read_text(encoding='utf-8')

    def test_width_comes_from_every_word(self):
        self.assertIn('widget.setFixedWidth(wide(widget,widget.text(),*START_WORDS))', self.text)

    def test_decided_as_the_render_begins_and_held_while_it_runs(self):
        submit = self.text[self.text.index('    def _submit('):]
        held = submit.index('self._pausing=self._pauses(output)')
        self.assertLess(held, submit.index('self._set_rendering(True)'))

    def test_the_rule_reads_xpu2_and_safe_denoising(self):
        method = self.text[self.text.index('    def _pauses('):self.text.index('    def _smart_on(')]
        self.assertIn("denoising.settings(self._settings_values()['denoising'])['safe']", method)
        self.assertIn('self._xpu2_previews()', method)
        self.assertIn('realtime=self._following or self.ipr_mode.isChecked()', method)

    def test_the_button_says_it_and_a_pause_is_a_stop_that_keeps(self):
        rendering = self.text[self.text.index('    def _set_rendering('):self.text.index('    def _submit(')]
        self.assertIn('start_word(active,again,paused and not self._following)', rendering)
        self.assertIn('PAUSE_TIP', rendering)
        self.assertIn("'Pausing'", rendering)
        # Pause goes the way Stop goes: XPU2 drains, saving where it stands, and Continue resumes from that.
        self.assertIn("if self._rendering or self._following:", self.text)
        stop = self.text[self.text.index('    def stop(self):'):self.text.index('    def _render_afresh(')]
        self.assertIn("'Pausing: saving the render where it stands.'", stop)
        self.assertIn('self.renderer.keep_progress()', stop)


if __name__ == '__main__':
    unittest.main()
