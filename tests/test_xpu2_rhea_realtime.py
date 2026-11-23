"""XPU2 RT (Rhea): Rhea as XPU2's realtime engine by default (Preferences: XPU2 RT engine), XPU2 RT following a drag of
the viewport's camera when chosen (XPU2 RT follows drags, off by default), Rhea's outputs written only into realtime
scenes XPU2 renders with Rhea, the session told the engine, and the status saying "XPU2 Rhea active" while Rhea renders
realtime."""
import sys
import types
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'kit/MoonRayForModo/python/moonray_modo'

try:
    from moonray_modo import preferences
except ImportError:
    # Without Qt: only what the module names when it is read, taken away at once (as test_moonlightipr_follow_drags).
    qt = types.ModuleType('PySide2')
    qt.QtCore = types.SimpleNamespace(QSettings=None)
    qt.QtWidgets = types.SimpleNamespace(QDialog=object)
    sys.modules['PySide2'] = qt
    try:
        from moonray_modo import preferences
    finally:
        del sys.modules['PySide2']
        sys.modules.pop('moonray_modo.preferences', None)
        vars(sys.modules['moonray_modo']).pop('preferences', None)

from moonray_modo import native, rdla


class Store(dict):
    def value(self, key, default=None):
        return self.get(key, default)


def read(key, stored=None):
    held = preferences.Preferences.__new__(preferences.Preferences)
    held.store = Store() if stored is None else Store({key: stored})
    return held.get(key)


class Preferences(unittest.TestCase):
    def test_rhea_is_the_default_engine(self):
        self.assertEqual(read('xpu2/rt_engine'), 'rhea')
        self.assertEqual(read('xpu2/rt_engine', 'xpu2'), 'xpu2')

    def test_follow_drags_off_unless_chosen(self):
        self.assertIs(read('xpu2/follow_drags'), False)
        self.assertIs(read('xpu2/follow_drags', 'true'), True)

    def test_in_the_preferences_window(self):
        text = (SOURCE / 'preferences.py').read_text(encoding='utf-8')
        self.assertIn("combo('xpu2/rt_engine', [('Rhea', 'rhea'), ('XPU2', 'xpu2')]", text)
        self.assertIn("check('xpu2/follow_drags', 'XPU2 RT follows drags'", text)

    def test_the_session_is_told_the_engine(self):
        text = (SOURCE / 'native.py').read_text(encoding='utf-8')
        self.assertIn("'XPU2_SESSION_RT_ENGINE': xpu2_rt_engine()", text)


class Outputs(unittest.TestCase):
    def test_rheas_outputs(self):
        lines = '\n'.join(rdla.rhea_lines('C:/tmp/preview.rhea.exr'))
        for name in ('/rhea_emission', '/rhea_direct', '/rhea_albedo', '/rhea_depth_min', '/rhea_depth_max'):
            self.assertIn('RenderOutput("%s")' % name, lines)
        self.assertIn('["lpe"] = "C[<L.>O]"', lines)
        self.assertIn('["lpe"] = "C[DGS][<L.>O]"', lines)
        self.assertIn('["material_aov"] = "albedo"', lines)
        self.assertEqual(lines.count('["state_variable"] = 11'), 2)
        self.assertIn('["math_filter"] = 2', lines)
        self.assertIn('["math_filter"] = 3', lines)

    def test_only_realtime_xpu2_with_rhea_takes_them(self):
        text = (SOURCE / 'render.py').read_text(encoding='utf-8')
        self.assertIn("if snapshot['_xpu2'] and snapshot.get('_realtime') and not request['output'] and native.xpu2_rt_engine()=='rhea':", text)
        text = (SOURCE / 'rdla.py').read_text(encoding='utf-8')
        self.assertIn("if scene.get('_rhea_outputs') and not output_file:", text)


class Status(unittest.TestCase):
    def setUp(self):
        self.gpu, self.cpu = native._gpu, native._cpu
        native._gpu, native._cpu = (lambda: 'GPU'), (lambda: 'CPU')

    def tearDown(self):
        native._gpu, native._cpu = self.gpu, self.cpu

    def test_rhea_active_while_rhea_renders_realtime(self):
        log = ('MoonRay XPU2 preview session: CPU and GPU, adaptive passes on the host\n'
               "MoonRay XPU2: realtime by Rhea (persistent probes; XPU2's samples where they do not hold)\n")
        self.assertEqual(native.execution_status(log), 'XPU2 Rhea active (GPU + CPU)')

    def test_xpu2_active_again_when_a_frame_is_xpu2s_alone(self):
        log = ('MoonRay XPU2 preview session: CPU and GPU, adaptive passes on the host\n'
               "MoonRay XPU2: realtime by Rhea (persistent probes; XPU2's samples where they do not hold)\n"
               "MoonRay XPU2: frames by XPU2 alone, not Rhea's: not realtime\n")
        self.assertEqual(native.execution_status(log), 'XPU2 active (GPU + CPU)')

    def test_xpu2_active_without_rhea(self):
        log = 'MoonRay XPU2 preview session: CPU and GPU, adaptive passes on the host\n'
        self.assertEqual(native.execution_status(log), 'XPU2 active (GPU + CPU)')

    def test_rheas_own_line_replaces_xpu2s_status(self):
        # The session's rheaStatus: how much of the view the store knew, and whether XPU2 is teaching it now; the frame's
        # summary line after it ("realtime by Rhea: ...") leaves it.
        log = ('MoonRay XPU2 preview session: CPU and GPU, adaptive passes on the host\n'
               "MoonRay XPU2: realtime by Rhea (persistent probes; XPU2's samples where they do not hold)\n"
               '@@MODO_XPU2 RHEA 81 1\n'
               "MoonRay XPU2: realtime by Rhea: a move (the last picture moved), then XPU2's frame at rest stopped in 0.20 s\n")
        self.assertEqual(native.execution_status(log), 'Rhea · 81% of the view known · learning')
        self.assertEqual(native.execution_status(log + '@@MODO_XPU2 RHEA 97 0\n'), 'Rhea · 97% of the view known')
        # A scene Rhea does not take after it: XPU2's own status again.
        self.assertEqual(native.execution_status(log + "MoonRay XPU2: frames by XPU2 alone, not Rhea's: not realtime\n"),
                         'XPU2 active (GPU + CPU)')


class Drags(unittest.TestCase):
    def test_an_xpu2_drags_release_is_a_move_alone(self):
        # Its steps went as moves alone: the release too, the scene not read, hashed or written whole again; unmarked, so
        # XPU2's frame follows. Anything else edited (full, changed settings, a blurred preview) reads it the usual way.
        text = (SOURCE / 'panel.py').read_text(encoding='utf-8')
        self.assertIn("if (fast is None and not held and xdrag and not blurred and not full and not changed and reuse in (True,'transforms') and items", text)
        self.assertIn("if fast is not None:release_move=True;moved.update(items);self._drag_count('released as a move alone')", text)
        self.assertIn("elif release_move:", text)
        release = text.split('elif release_move:', 1)[1].split('elif fast is not None and xdrag:', 1)[0]
        self.assertIn('self._submit(scene,', release)
        self.assertNotIn('_xpu2_drag', release)

    def test_the_live_tick_follows_xpu2_drags(self):
        text = (SOURCE / 'panel.py').read_text(encoding='utf-8')
        self.assertIn('xdrag=not ipr and self._xpu2_drags()', text)
        self.assertIn('polled=self._camera_moved() if held and (ipr or xdrag) and not full else set()', text)
        self.assertIn("if not self.preferences.get('xpu2/follow_drags'):return False", text)
        # A step sent as it comes: not held at a first sample as MoonLightIPR's are.
        self.assertIn("elif fast is not None and xdrag:", text)


class Session(unittest.TestCase):
    def test_the_session_runs_rhea_for_realtime(self):
        text = (ROOT / 'xpu2/interactive/xpu2_session.cc').read_text(encoding='utf-8')
        self.assertIn('#include "../../rhea/rhea_realtime.h"', text)
        self.assertIn('else if (rheaNow)', text)
        # An edit forgets Rhea's picture; the camera alone whose plan was made again (geometry tessellated for the camera)
        # forgets only the probes, the last picture kept to move.
        self.assertIn('if (rheaWanted && fresh && !scene.cameraFrom) {', text)
        self.assertIn('if (scene.cameraEdit) rheaView.resetProbes();', text)
        self.assertIn('else rheaView.reset();', text)
        # What it last showed is kept through the reset: a frame with nothing to warp fades XPU2 in over it.
        self.assertIn('rheaView.screenWarp(*scene.plan);', text)
        self.assertIn('MoonRay XPU2: realtime by Rhea (', text)
        self.assertIn("MoonRay XPU2: frames by XPU2 alone, not Rhea's: ", text)


if __name__ == '__main__':
    unittest.main()
