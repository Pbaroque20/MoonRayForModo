"""MoonLightIPR's Render Animation writes each frame's EXR with its alpha (playblast.MoonLightIPRAnimation): once the
frame's beauty (and its denoised beauty, Denoiser on) has come, MoonLightIPR's alpha output is asked of the session (it
gathers every output beside the beauty, so it comes at once), appended as A, and the output looked at before is looked
at again. A report: its animations had no alpha."""
import os
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
for name in ('modo', 'lx', 'lxifc', 'lxu'):
    sys.modules.setdefault(name, types.ModuleType(name))
RUNTIME = ROOT / 'dist/personal-kit/Luxology/Kits/MoonRayForModo/runtime'


def _playblast(test):
    """playblast with Qt stood in for by plain classes, only while a test runs."""
    qt = types.ModuleType('PySide2')
    core = types.ModuleType('PySide2.QtCore')
    core.QObject = object
    core.Signal = lambda *a, **k: None
    core.QTimer = mock.MagicMock()

    class Settings:
        """The kit's stored settings: none, so each its default."""

        def __init__(self, *args, **kwargs):
            pass

        def value(self, key, default=None, *args, **kwargs):
            return default

        def setValue(self, *args, **kwargs):
            pass
    core.QSettings = Settings
    stubs = {'PySide2': qt, 'PySide2.QtCore': core, 'PySide2.QtGui': mock.MagicMock(), 'PySide2.QtWidgets': mock.MagicMock()}
    qt.QtCore, qt.QtGui, qt.QtWidgets = core, stubs['PySide2.QtGui'], stubs['PySide2.QtWidgets']
    # Modo's own modules, as far as playblast's imports (animation, host) reach for them.
    if 'lxu.utils' not in sys.modules:
        lxu = types.ModuleType('lxu')
        lxu.__path__ = []
        lxu.utils = types.ModuleType('lxu.utils')
        stubs.update({'lxu': lxu, 'lxu.utils': lxu.utils})
    held = {name: sys.modules.get(name) for name in list(stubs) + ['moonray_modo.playblast']}
    sys.modules.update(stubs)
    sys.modules.pop('moonray_modo.playblast', None)

    def restore():
        for name, module in held.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        package = sys.modules.get('moonray_modo')
        if package is not None and held['moonray_modo.playblast'] is None and hasattr(package, 'playblast'):
            delattr(package, 'playblast')
    test.addCleanup(restore)
    from moonray_modo import playblast
    return playblast


class Session:
    def __init__(self):
        self.aov_now = (0, 'none')
        self.asked = []

    def aov(self, kind, key):
        self.aov_now = (int(kind), str(key) if kind else 'none')
        self.asked.append(self.aov_now)


class Animation:
    """What _settled uses of a MoonLightIPRAnimation, the frame's pictures given by the test."""

    def __init__(self, denoise):
        self.running, self.quiet, self.denoise, self.frame, self.directory = True, 0, denoise, 1, 'frames'
        self.frames, self.total, self.completed = [1], 1, []
        self.poll = mock.MagicMock()
        self.done = mock.MagicMock()
        self.session = Session()
        buffers = types.SimpleNamespace(busy=lambda: False)
        self.panel = types.SimpleNamespace(renderer=types.SimpleNamespace(moonlightipr_frame=None, buffers=buffers, moonlightipr=self.session),
                                           status=mock.MagicMock())
        self.shown, self.pictures, self.alphas, self.written = [], {'beauty': ('b',)}, {}, []
        self.panel._moonlightipr_linear = lambda key: self.alphas.get(key)

    def _picture(self):
        return self.pictures['beauty']

    def _alpha_ticked(self):
        return True

    def _show(self, wanted):
        self.shown.append(wanted)

    def _write(self, linear, denoised=False, alpha=None):
        self.written.append((linear, denoised, alpha))
        return 'frame.exr' if not denoised else 'frame.denoised.exr'

    def stop(self):
        self.running = False

    def failed(self, message):
        self.failure = message

    def settle(self, playblast, times=3):
        for _ in range(times):
            playblast.MoonLightIPRAnimation._settled(self)


class Settling(unittest.TestCase):
    def setUp(self):
        self.playblast = _playblast(self)

    def fresh(self, denoise):
        a = Animation(denoise)
        self.playblast.MoonLightIPRAnimation._fresh(a)
        return a

    def test_the_alpha_is_asked_once_the_beauty_has_come_and_written_as_a(self):
        a = self.fresh(False)
        a.settle(self.playblast)
        self.assertEqual(a.session.asked, [(9, 'alpha')], 'the alpha asked of the session')
        self.assertEqual(a.written, [], 'nothing written before it comes')
        a.alphas['alpha'] = ('a',)
        a.settle(self.playblast)
        self.assertEqual(a.written, [(('b',), False, ('a',))])
        self.assertEqual(a.session.aov_now, (0, 'none'), 'the beauty looked at again')

    def test_with_the_denoiser_both_exrs_take_the_alpha(self):
        a = self.fresh(True)
        a.settle(self.playblast)
        self.assertEqual(a.shown, ['denoised_beauty'])
        a.pictures['beauty'] = ('d',)  # the denoised picture comes under the beauty's name
        a.settle(self.playblast)
        self.assertEqual(a.session.asked, [(9, 'alpha')])
        a.alphas['alpha'] = ('a',)
        a.settle(self.playblast)
        self.assertEqual(a.written, [(('b',), False, ('a',)), (('d',), True, ('a',))])

    def test_alpha_unticked_in_render_settings_is_not_asked_for(self):
        # Render Settings' MoonLightIPR Outputs (AOVs): Alpha unticked, the frames are written without it.
        a = self.fresh(False)
        a._alpha_ticked = lambda: False
        a.settle(self.playblast)
        self.assertEqual(a.session.asked, [])
        self.assertEqual(a.written, [(('b',), False, None)])

    def test_no_alpha_in_a_minute_writes_the_frame_without_it(self):
        a = self.fresh(False)
        a.settle(self.playblast)
        a.settle(self.playblast, times=1600)
        self.assertEqual(a.written, [(('b',), False, None)])


@unittest.skipUnless((RUNTIME / 'oiiotool.exe').is_file(), 'the staged runtime')
class Writing(unittest.TestCase):
    def test_the_exr_has_r_g_b_and_a(self):
        playblast = _playblast(self)
        with tempfile.TemporaryDirectory() as folder:
            width, height = 4, 2
            beauty = (width, height, struct.pack('<%df' % (width * height * 3), *([0.5] * width * height * 3)))
            alpha = (width, height, struct.pack('<%df' % (width * height * 3), *([0.25] * width * height * 3)))
            a = types.SimpleNamespace(directory=Path(folder), prefix='frame', frame=1, digits=4, export_as=None, denoise=False,
                                      panel=types.SimpleNamespace(renderer=types.SimpleNamespace(active={'runtime': str(RUNTIME)})))
            written = playblast.MoonLightIPRAnimation._write(a, beauty, alpha=alpha)
            from moonray_modo import native
            info = subprocess.run([str(RUNTIME / 'oiiotool.exe'), '--info', '-v', written], env=native.environment(RUNTIME),
                                  stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.decode(errors='replace')
            self.assertIn('R, G, B, A', info)

    def test_a_png_beside_it_keeps_the_alpha_the_exr_has(self):
        # A GUI check found the PNG of "OpenEXR, and PNG" written without its alpha, the EXR beside it with it.
        playblast = _playblast(self)
        from moonray_modo import native
        width, height = 4, 2
        for alpha, channels in (((width, height, struct.pack('<%df' % (width * height * 3), *([0.25] * width * height * 3))), 'R, G, B, A'),
                                (None, 'R, G, B')):
            with tempfile.TemporaryDirectory() as folder:
                beauty = (width, height, struct.pack('<%df' % (width * height * 3), *([0.5] * width * height * 3)))
                a = types.SimpleNamespace(directory=Path(folder), prefix='frame', frame=1, digits=4, export_as={'type': 'png8'}, denoise=False,
                                          panel=types.SimpleNamespace(renderer=types.SimpleNamespace(active={'runtime': str(RUNTIME)}, buffers=None)))
                playblast.MoonLightIPRAnimation._write(a, beauty, alpha=alpha)
                png = next(Path(folder).glob('*.png'))
                info = subprocess.run([str(RUNTIME / 'oiiotool.exe'), '--info', '-v', str(png)], env=native.environment(RUNTIME),
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.decode(errors='replace').replace('\r', '')
                self.assertIn('channel list: ' + channels + '\n', info, channels)


if __name__ == '__main__':
    unittest.main()
