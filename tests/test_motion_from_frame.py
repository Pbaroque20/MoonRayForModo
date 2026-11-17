"""The scene with its motion made from a reading of the frame already in hand (animation.capture_frame's frame): in a
scene whose meshes hold through the shutter, only the shutter's ends are asked of Modo, with the meshes kept, and the
reading handed in is left as it was. MoonLightIPR's realtime read a driving car whole a second time at each edit, after
reading the edit itself (8-9 s each in Modo)."""
import pathlib
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
STUBS = {}
try:
    from moonray_modo import animation
except ImportError:  # no Qt or Modo outside Modo
    qt = types.ModuleType('PySide2')
    qt.QtCore = types.ModuleType('QtCore')
    qt.QtCore.QObject = object
    STUBS = {'PySide2': qt, 'PySide2.QtCore': qt.QtCore, 'lx': types.ModuleType('lx'),
             'moonray_modo.host': types.ModuleType('moonray_modo.host')}
    with mock.patch.dict(sys.modules, STUBS):
        from moonray_modo import animation
from moonray_modo import incremental  # noqa: E402

IDENTITY = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def placed(z):
    matrix = list(IDENTITY)
    matrix[14] = z
    return matrix


def reading(z):
    return {'camera': {'identity': 'cam', 'matrix': list(IDENTITY), 'focal_mm': 50.0, 'shutter_length': 0.5},
            'meshes': [{'identity': 'car|m|0', 'name': 'Car', 'faces': [[0, 1, 2]], 'vertices': [[0, 0, 0], [1, 0, 0], [0, 1, 0]],
                        'material': 'm', 'matrix': placed(z)}],
            'materials': {'m': {}}, 'lights': [], 'warnings': []}


class FromTheFrame(unittest.TestCase):
    def run_capture(self, frame):
        moment = SimpleNamespace(time=1.0)
        selection = SimpleNamespace(GetTime=lambda: moment.time, SetTime=lambda value: setattr(moment, 'time', value))
        fake_lx = types.SimpleNamespace(service=SimpleNamespace(Selection=lambda: selection))
        asked = []

        def snapshot(evaluated_geometry=False, reuse_geometry=None, **kwargs):
            asked.append(reuse_geometry is not None)
            if reuse_geometry is None:
                return reading(0.0)
            value = dict(reuse_geometry, meshes=[dict(mesh) for mesh in reuse_geometry['meshes']])
            return value
        properties = types.ModuleType('moonray_modo.properties')
        properties.scene_settings = lambda: {}
        extra = types.ModuleType('moonray_modo.extra_geometry')
        extra.attach = lambda value, controls: None
        modo = types.ModuleType('modo')
        modo.Scene = lambda: SimpleNamespace(fps=24.0)
        where = {}

        def matrices(scene, snapshot):
            return {'car': placed(where.get('z', 0.0))}

        def follow(scene, sample, before):
            sample['meshes'][0]['matrix'] = placed(moment_z(moment.time))

        def moment_z(time):
            return (time - 1.0) * 24.0     # a metre a frame along Z
        package = sys.modules['moonray_modo']
        # Stubbed in the package too: "from . import properties" takes the package's own once another test has imported it.
        with mock.patch.object(animation, 'lx', fake_lx), \
                mock.patch.object(animation, 'host', SimpleNamespace(snapshot=snapshot)), \
                mock.patch.dict(sys.modules, {'moonray_modo.properties': properties, 'moonray_modo.extra_geometry': extra, 'modo': modo}), \
                mock.patch.object(package, 'properties', properties, create=True), \
                mock.patch.object(package, 'extra_geometry', extra, create=True), \
                mock.patch.object(incremental, 'rigid', lambda scene, snap: True), \
                mock.patch.object(incremental, 'item_matrices', matrices), \
                mock.patch.object(incremental, 'follow_items', follow):
            result = animation.capture_frame(1.0, False, True, 24.0, preview=True, frame=frame)
        return result, asked, moment

    def test_the_frame_handed_in_is_taken_and_only_the_ends_are_asked(self):
        frame = reading(0.0)
        result, asked, moment = self.run_capture(frame)
        # The two ends of the shutter, each with the meshes kept; the frame not read again.
        self.assertEqual(asked, [True, True])
        mesh = result['meshes'][0]
        self.assertAlmostEqual(mesh['matrix'][14], -0.25)
        self.assertAlmostEqual(mesh['matrix_close'][14], 0.25)
        self.assertEqual(mesh['matrix_frame'][14], 0.0)
        # The time put back, and the reading handed in left as it was.
        self.assertEqual(moment.time, 1.0)
        self.assertNotIn('matrix_close', frame['meshes'][0])
        self.assertNotIn('motion_steps', frame)

    def test_without_a_frame_it_is_read_first(self):
        _, asked, _ = self.run_capture(None)
        self.assertEqual(asked, [False, True, True])


if __name__ == '__main__':
    unittest.main()
