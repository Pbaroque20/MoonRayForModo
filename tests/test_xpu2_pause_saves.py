"""XPU2 paused under Safe Denoising is taken up by Continue.

Two faults made Pause a plain stop and Continue a render from the start: the stop and its keeping asked whether XPU2
rendered the pass of the request's snapshot (Renderer.active), which never has the mark (the pass's own copy has it);
and what XPU2 saved was left where it wrote it, among the render's files, which are let go of once the next render is
under way (_persistent_applied), before XPU2 read them. Its saves are now kept aside as MoonRay's are.

render.py needs Qt: the method is read from the file and run here on its own."""
import ast
import shutil
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
RENDER = ROOT / 'kit/MoonRayForModo/python/moonray_modo/render.py'
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from moonray_modo import denoising  # noqa: E402


def method(name):
    tree = ast.parse(RENDER.read_text(encoding='utf-8'))
    renderer = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'Renderer')
    found = next(node for node in renderer.body if isinstance(node, ast.FunctionDef) and node.name == name)
    space = {'Path': Path, 'denoising': denoising, 'tempfile': tempfile, 'uuid': uuid, 'shutil': shutil}
    exec(compile(ast.Module(body=[found], type_ignores=[]), str(RENDER), 'exec'), space)
    return space[name]


class KeptAside(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.keep = method('_keep_xpu2_saves')
        base = Path(self.folder.name) / 'abc123'
        self.files = [base.with_suffix('.beauty.exr'), base.with_suffix('.albedo.exr'), base.with_suffix('.resume-data.exr')]
        self.renderer = SimpleNamespace(safe_files=self.files, current_base=base, resumable_before=None)
        self.renderer._safe_key = lambda path: Path(path).name[len(base.name):]

    def tearDown(self):
        held = getattr(self.renderer, 'resume_directory', None)
        if held is not None:
            held.cleanup()

    def saved(self, resume=True):
        for path in self.files:
            Path(denoising.safe_name(path)).write_bytes(b'saved ' + path.name.encode())
        if resume:
            Path(denoising.safe_name(self.files[0]) + '.xpu2resume').write_bytes(b'generations')

    def test_kept_aside_survive_the_render_files_being_let_go(self):
        self.saved()
        kept = self.keep(self.renderer)
        self.assertEqual(set(kept), {'.beauty.exr', '.albedo.exr', '.resume-data.exr'})
        # The next render under way lets go of this one's files (_persistent_applied).
        for path in Path(self.folder.name).glob('abc123*'):
            path.unlink()
        for key, path in kept.items():
            self.assertEqual(Path(path).read_bytes(), b'saved abc123' + key.encode())
        # Where its generations stood, beside the file XPU2 is told to resume from (resume_file_name).
        self.assertEqual(Path(kept['.beauty.exr'] + '.xpu2resume').read_bytes(), b'generations')
        self.assertFalse(Path(kept['.albedo.exr'] + '.xpu2resume').exists())

    def test_nothing_kept_without_where_the_generations_stood_or_with_a_file_missing(self):
        self.saved(resume=False)
        self.assertIsNone(self.keep(self.renderer))
        self.saved()
        Path(denoising.safe_name(self.files[1])).unlink()
        self.assertIsNone(self.keep(self.renderer))

    def test_an_earlier_pause_is_let_go_once_there_is_a_newer_save(self):
        self.saved()
        first = self.keep(self.renderer)
        self.renderer.resumable_before = first
        self.saved()
        second = self.keep(self.renderer)
        self.assertTrue(all(Path(path).is_file() for path in second.values()))
        self.assertFalse(any(Path(path).exists() for path in first.values()))
        self.assertFalse(Path(first['.beauty.exr'] + '.xpu2resume').exists())
        self.assertIsNone(self.renderer.resumable_before)


class WaitedForAsLongAsItsSaveTakes(unittest.TestCase):
    def test_xpu2_paused_on_a_big_picture_with_many_outputs_is_given_its_save(self):
        wait = method('keep_wait')
        # The test scene's preview: 28 checkpoint files at 1280 x 720, cut at 16 seconds with its save half written; it
        # took 17 in all.
        paused = SimpleNamespace(active={'width': 1280, 'height': 720}, pass_xpu2=True, safe_files=[Path('f')] * 28)
        self.assertEqual(wait(paused), 120000)
        # A 4K picture with as many outputs: three saves' worth and 30 seconds.
        big = SimpleNamespace(active={'width': 3840, 'height': 2160}, pass_xpu2=True, safe_files=[Path('f')] * 28)
        self.assertEqual(wait(big), int(1000 * (30 + 3 * .25 * 28 * 3840 * 2160 / 1e6)))
        # Any other stop that keeps the picture waits as before.
        self.assertEqual(wait(SimpleNamespace(active={'width': 1280, 'height': 720}, pass_xpu2=False, safe_files=[Path('f')] * 28)), 16000)
        self.assertEqual(wait(SimpleNamespace(active={'width': 1280, 'height': 720}, pass_xpu2=True, safe_files=[])), 16000)

    def test_the_window_waits_by_it(self):
        panel = (ROOT / 'kit/MoonRayForModo/python/moonray_modo/panel.py').read_text(encoding='utf-8')
        stop = panel[panel.index('    def stop(self):'):panel.index('    def _render_afresh(')]
        self.assertIn('self.renderer.keep_progress():', stop)
        self.assertIn('self._await_settle(self.renderer.keep_wait())', stop)


class ThePassSaysXpu2(unittest.TestCase):
    def setUp(self):
        self.text = RENDER.read_text(encoding='utf-8')

    def test_never_asked_of_the_request(self):
        self.assertNotIn("self.active['snapshot'].get('_xpu2')", self.text)

    def test_held_as_the_pass_begins_and_read_by_the_stop_and_its_keeping(self):
        begin = self.text[self.text.index('    def _begin_pass('):]
        self.assertLess(begin.index("snapshot['_xpu2']=bool("), begin.index("self.pass_xpu2=snapshot['_xpu2']"))
        keep = self.text[self.text.index('    def keep_progress('):self.text.index('    def settle_moonray(')]
        self.assertIn("getattr(self,'pass_xpu2',False) and getattr(self,'safe_files',None)", keep)
        exited = self.text[self.text.index('    def _exited('):]
        self.assertIn("getattr(self,'pass_xpu2',False)", exited[:exited.index('if getattr(self,\'settling\'')])
        self.assertIn('kept=self._keep_xpu2_saves()', exited)

    def test_paused_is_said_where_complete_was(self):
        end = self.text[self.text.index('    def _progress_end('):self.text.index('    def _started(')]
        self.assertIn("'Paused · Elapsed '", end)
        self.assertLess(end.index("'Paused · Elapsed '"), end.index("'Complete' if success"))


if __name__ == '__main__':
    unittest.main()
