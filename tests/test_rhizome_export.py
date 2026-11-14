"""The Rhizome window's export (rhizome_window.export_job) hands the master the geometry's lists as binary, as the preview
hands them to XPU2 (rdlb.py), and takes a reading the Scene cache kept (scene_reading). A tester's Lamborghini took
minutes to export for Rhizome, every point formatted as text, where the preview started at once."""
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


def _stub_modules(test):
    """Qt stand-ins for the window module, only while a test runs: left in place, they took the place of other tests'
    own (test_xpu2_retry's)."""
    qt = types.ModuleType('PySide2')
    stubs = {'PySide2': qt}
    for name in ('QtCore', 'QtGui', 'QtWidgets'):
        stubs['PySide2.' + name] = mock.MagicMock()
        setattr(qt, name, stubs['PySide2.' + name])
    held = {name: sys.modules.get(name) for name in list(stubs) + ['moonray_modo.rhizome_window']}
    sys.modules.update(stubs)
    sys.modules.pop('moonray_modo.rhizome_window', None)

    def restore():
        for name, module in held.items():
            if module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = module
        package = sys.modules.get('moonray_modo')
        if package is not None and held['moonray_modo.rhizome_window'] is None and hasattr(package, 'rhizome_window'):
            delattr(package, 'rhizome_window')
    test.addCleanup(restore)


class Selection:
    def __init__(self):
        self.time = 0.0

    def GetTime(self):
        return self.time

    def SetTime(self, value):
        self.time = value


class Record:
    def __init__(self, data):
        self.data = data

    def bytes(self):
        return self.data


class ExportJob(unittest.TestCase):
    def setUp(self):
        _stub_modules(self)
        from moonray_modo import rhizome_window, rdlb
        self.window, self.rdlb = rhizome_window, rdlb
        self.selection = Selection()
        self.lx = types.SimpleNamespace(service=types.SimpleNamespace(Selection=lambda: self.selection))
        self.modo = types.SimpleNamespace(Scene=lambda: types.SimpleNamespace(fps=24.0))
        self.folder = Path(tempfile.mkdtemp())
        self.read = []
        self.binary = True
        self.empty_frames = set()

    def snapshot(self, evaluated_geometry=False):
        self.read.append(self.selection.time)
        return {'width': 64, 'height': 36, 'meshes': []}

    def scene_text(self, scene, width, height, samples, environment, output):
        frame = round(self.selection.time * 24)
        if self.rdlb._SINK is not None and frame not in self.empty_frames:
            self.rdlb._SINK.objects['mesh'] = Record(b'points of frame %d' % frame)
            return '-- rdlb ["vertex_list"]\n'
        return 'vertex_list = {1, 2, 3}\n'

    def export(self, frames, kept=None):
        settings = {'surface': 2, 'samples': 4, 'environment': 0.1}
        import moonray_modo
        from moonray_modo import native, rdla, scene_reading, scene_setup
        # host reads Modo through its SDK (lxu.utils), which tests do not have: a stand-in with its snapshot.
        host = types.ModuleType('moonray_modo.host')
        host.snapshot = self.snapshot
        with mock.patch.dict(sys.modules, {'lx': self.lx, 'modo': self.modo, 'moonray_modo.host': host}), \
                mock.patch.object(moonray_modo, 'host', host, create=True), \
                mock.patch.object(scene_setup, 'values', lambda: dict(settings)), \
                mock.patch.object(scene_setup, 'configure', lambda snapshot, held: snapshot), \
                mock.patch.object(rdla, 'scene_text', self.scene_text), \
                mock.patch.object(native, 'binary_geometry', lambda: self.binary), \
                mock.patch.object(scene_reading, 'key', lambda evaluated: ('frame', self.selection.time)), \
                mock.patch.object(scene_reading, 'load', lambda key: kept), \
                mock.patch.object(scene_reading, 'keep', lambda *a: None):
            return self.window.export_job(self.folder, 'shot', frames)

    def test_frames_go_with_their_geometry_as_binary(self):
        scenes, out = self.export([1, 2])
        job = self.folder / 'job'
        self.assertEqual([p.name for p in scenes], ['shot.####.rdla', 'shot.####.rdlb'])
        self.assertEqual(out.name, 'shot.####.pfm')
        for frame in (1, 2):
            self.assertIn('-- rdlb', (job / ('shot.%04d.rdla' % frame)).read_text())
            self.assertIn(b'points of frame %d' % frame, (job / ('shot.%04d.rdlb' % frame)).read_bytes())

    def test_a_frame_without_geometry_still_has_its_binary_file(self):
        self.empty_frames = {1}
        scenes, _ = self.export([1, 2])
        job = self.folder / 'job'
        self.assertEqual(len(scenes), 2)
        self.assertEqual((job / 'shot.0001.rdlb').read_bytes(), self.rdlb.Sink().payload())

    def test_binary_switched_off_writes_text_and_leaves_no_stale_binary(self):
        job = self.folder / 'job'
        job.mkdir()
        (job / 'shot.rdlb').write_bytes(b'stale')
        self.binary = False
        scenes, _ = self.export([None])
        self.assertEqual([p.name for p in scenes], ['shot.rdla'])
        self.assertIn('vertex_list = {1, 2, 3}', (job / 'shot.rdla').read_text())
        self.assertFalse((job / 'shot.rdlb').exists())

    def test_a_kept_reading_is_taken_instead_of_reading_modo(self):
        scenes, _ = self.export([None], kept={'width': 64, 'height': 36, 'meshes': [], '_full_capture': True})
        self.assertEqual(self.read, [])
        self.assertTrue((self.folder / 'job' / 'shot.rdlb').is_file())


class RangeChecks(unittest.TestCase):
    """The checks that took a car's export seconds in Python (rdla.checked, rdlb.int_list), as rows gives them, with the
    adapter or without it."""

    def test_without_the_adapter_python_answers_the_same(self):
        from array import array
        from moonray_modo import rdlb, rows
        with mock.patch.object(rows, '_native', lambda: None), mock.patch.object(rows, 'NATIVE', None):
            self.assertEqual(rows.least(array('i', [4, 3, 7])), 3)
            self.assertEqual(rows.least(array('i')), 0)
            self.assertIsNone(rows.zigzag4(array('i', [1, 2])))
            self.assertEqual(rdlb.int_list(array('i', [0, 5, -1])), rdlb.vl(3) + rdlb.zigzag(0) + rdlb.zigzag(5) + rdlb.zigzag(-1))

    def test_unsigned_reads_negative_corners_as_out_of_range(self):
        from array import array
        from moonray_modo import rows
        bits = rows.unsigned(array('i', [0, 2, -1]))
        self.assertEqual(bits.typecode, 'I')
        self.assertGreaterEqual(max(bits), 1 << 31)
        same = array('I', [1, 2])
        self.assertIs(rows.unsigned(same), same)
        self.assertIsNone(rows.unsigned(array('f', [1.0])))

    def test_the_adapter_matches_python(self):
        from array import array
        from moonray_modo import rdlb, rows
        native = rows._native()
        if native is None or not hasattr(native, 'MR_least'):
            self.skipTest('no geometry adapter with MR_least here')
        values = array('i', [9, 3, 1 << 26, 0, 7])
        self.assertEqual(rows.least(values), 0)
        self.assertEqual(rows.least(array('i', [-5, 2])), -5)
        self.assertEqual(rows.most(rows.unsigned(values)), 1 << 26)
        with mock.patch.object(rows, '_native', lambda: None), mock.patch.object(rows, 'NATIVE', None):
            python = rdlb.int_list(values)
        self.assertEqual(rdlb.int_list(values), python)
        self.assertEqual(rdlb.int_list(array('l', [3, -2])), rdlb.vl(2) + rdlb.zigzag(3) + rdlb.zigzag(-2))


if __name__ == '__main__':
    unittest.main()
