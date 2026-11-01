"""The Render Animation window's values, frame names and the folder its sequences share. No Modo."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python'))
from moonray_modo import denoising, sequence_plan

EXR = b'\x76\x2f\x31\x01' + b'0' * 64
SCENE = {'first': 1, 'last': 120, 'step': 1, 'fps': 30.0, 'motion': True}


class WindowValues(unittest.TestCase):
    def test_a_new_scene_opens_with_its_own_settings(self):
        values = sequence_plan.window_values({}, SCENE)
        self.assertEqual({key: values[key] for key in SCENE}, SCENE)
        self.assertEqual((values['prefix'], values['digits']), ('frame', 6))

    def test_what_was_rendered_with_stays_while_the_scene_is_as_it_was(self):
        held = {'folder': 'D:/out', 'prefix': 'shot', 'digits': 4, 'first': 10, 'last': 20, 'step': 2, 'fps': 24.0, 'motion': False, 'scene': dict(SCENE)}
        values = sequence_plan.window_values(held, SCENE)
        self.assertEqual((values['first'], values['last'], values['step'], values['fps'], values['motion']), (10, 20, 2, 24.0, False))
        self.assertEqual((values['folder'], values['prefix'], values['digits']), ('D:/out', 'shot', 4))

    def test_the_scene_changed_since_is_followed_and_the_names_stay(self):
        held = {'folder': 'D:/out', 'prefix': 'shot', 'digits': 4, 'first': 10, 'last': 20, 'step': 2, 'fps': 24.0, 'motion': False, 'scene': dict(SCENE)}
        values = sequence_plan.window_values(held, dict(SCENE, last=240))
        self.assertEqual((values['first'], values['last'], values['fps'], values['motion']), (1, 240, 30.0, True))
        self.assertEqual((values['folder'], values['prefix'], values['digits']), ('D:/out', 'shot', 4))


class FrameNames(unittest.TestCase):
    def test_digits_fill_the_number_with_zeros(self):
        self.assertEqual(sequence_plan.frame_name('frame', 1), 'frame.000001.exr')
        self.assertEqual(sequence_plan.frame_name('frame', 12, 4), 'frame.0012.exr')
        self.assertEqual(sequence_plan.frame_name('frame', 12345, 3), 'frame.12345.exr')

    def test_the_plan_looks_for_frames_by_their_digits(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'frame.0001.exr').write_bytes(b'\x76\x2f\x31\x01' + b'0' * 64)
            self.assertEqual(sequence_plan.plan(folder, 1, 2, 1, 'frame', 24, False, digits=6)[0], [1, 2])
            with self.assertRaises(ValueError):
                sequence_plan.plan(folder, 1, 2, 1, 'frame', 24, False, digits=4)


class DenoisedNames(unittest.TestCase):
    def test_the_frame_number_stays_last(self):
        self.assertEqual(denoising.sidecar('D:/out/shot.001.exr').name, 'shot.denoised.001.exr')
        self.assertEqual(denoising.sidecar('D:/out/shot.-0012.exr').name, 'shot.denoised.-0012.exr')

    def test_a_composite_is_named_the_same_way(self):
        from moonray_modo.composite_output import beside
        self.assertEqual(beside('D:/out/shot.001.exr').name, 'shot.composite.001.exr')
        self.assertEqual(beside('D:/out/shot.exr').name, 'shot.composite.exr')

    def test_a_still_has_no_number_to_keep_last(self):
        self.assertEqual(denoising.sidecar('D:/out/shot.exr').name, 'shot.denoised.exr')

    def test_a_sequence_begun_under_the_old_name_is_still_recognised(self):
        with tempfile.TemporaryDirectory() as folder:
            frame = Path(folder) / 'shot.0001.exr'
            self.assertEqual(denoising.held_sidecar(frame).name, 'shot.denoised.0001.exr')
            (Path(folder) / 'shot.0001.denoised.exr').write_bytes(b'x')
            self.assertEqual(denoising.held_sidecar(frame).name, 'shot.0001.denoised.exr')

    def test_a_resumed_frame_counts_its_denoised_copy(self):
        with tempfile.TemporaryDirectory() as folder:
            sequence_plan.manifest_path(folder, 'shot').write_text(json.dumps({'signature': 's', 'first': 1, 'last': 1, 'step': 1, 'prefix': 'shot', 'fps': 24, 'motion_blur': False, 'digits': 4}))
            (Path(folder) / 'shot.0001.exr').write_bytes(EXR)
            (Path(folder) / 'shot.denoised.0001.exr').write_bytes(EXR)
            pending, completed = sequence_plan.plan(folder, 1, 1, 1, 'shot', 24, False, True, True, 's', 4)
            self.assertEqual((pending, len(completed)), ([], 1))


class PictureOnly(unittest.TestCase):
    RECORD = {'signature': 's', 'first': 1, 'last': 2, 'step': 1, 'prefix': 'shot', 'fps': 24, 'motion_blur': False, 'digits': 4, 'picture': 'png8'}

    def plan(self, folder, picture='png8', missing=False, signature=None):
        return sequence_plan.plan(folder, 1, 2, 1, 'shot', 24, False, missing, False, signature, 4, picture)

    def test_the_name_takes_the_types_extension(self):
        self.assertEqual(sequence_plan.frame_name('shot', 12, 4, 'jpg'), 'shot.0012.jpg')

    def test_a_new_sequence_has_every_frame_to_render(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(self.plan(folder)[0], [1, 2])

    def test_a_picture_already_there_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'shot.0001.png').write_bytes(b'x')
            with self.assertRaisesRegex(ValueError, 'Output exists'):
                self.plan(folder)

    def test_an_exr_it_did_not_render_is_never_taken_for_its_own(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'shot.0001.exr').write_bytes(EXR)
            with self.assertRaisesRegex(ValueError, 'Output exists'):
                self.plan(folder)
            with self.assertRaisesRegex(ValueError, 'Output exists'):
                self.plan(folder, missing=True, signature='s')

    def test_resuming_keeps_the_pictures_and_renders_the_rest(self):
        with tempfile.TemporaryDirectory() as folder:
            sequence_plan.manifest_path(folder, 'shot').write_text(json.dumps(self.RECORD))
            (Path(folder) / 'shot.0001.png').write_bytes(b'x')
            (Path(folder) / 'shot.0002.exr').write_bytes(EXR)
            pending, completed = self.plan(folder, missing=True, signature='s')
            self.assertEqual(pending, [2])
            self.assertEqual(Path(completed[0]['file']).name, 'shot.0001.png')

    def test_resuming_in_another_type_is_refused(self):
        with tempfile.TemporaryDirectory() as folder:
            sequence_plan.manifest_path(folder, 'shot').write_text(json.dumps(self.RECORD))
            with self.assertRaisesRegex(ValueError, 'picture'):
                self.plan(folder, picture='jpg', missing=True, signature='s')

    def test_only_what_the_frame_was_made_from_goes(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            for name in ('shot.0001.exr', 'shot.denoised.0001.exr', 'shot.0001.png', 'shot.0002.exr', 'shot.composite.0001.exr'):
                (folder / name).write_bytes(b'x')
            (folder / 'shot.0001.exr.postprocess').mkdir()
            (folder / 'shot.0001.exr.postprocess' / 'manifest.json').write_text('{}')
            sequence_plan.let_go(folder / 'shot.0001.exr')
            self.assertEqual(sorted(path.name for path in folder.iterdir()), ['shot.0001.png', 'shot.0002.exr', 'shot.composite.0001.exr'])


class SharedFolder(unittest.TestCase):
    def test_two_prefixes_share_a_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            sequence_plan.manifest_path(folder, 'first').write_text(json.dumps({'prefix': 'first'}))
            (Path(folder) / 'first.000001.exr').write_bytes(b'\x76\x2f\x31\x01' + b'0' * 64)
            self.assertEqual(sequence_plan.plan(folder, 1, 2, 1, 'second', 24, False)[0], [1, 2])

    def test_the_same_prefix_is_still_refused_and_says_what_to_do(self):
        with tempfile.TemporaryDirectory() as folder:
            sequence_plan.manifest_path(folder, 'first').write_text(json.dumps({'prefix': 'first'}))
            with self.assertRaisesRegex(ValueError, 'another file prefix'):
                sequence_plan.plan(folder, 1, 2, 1, 'first', 24, False)

    def test_a_record_from_before_goes_for_its_own_prefix_alone(self):
        with tempfile.TemporaryDirectory() as folder:
            (Path(folder) / 'moonray-sequence.json').write_text(json.dumps({'prefix': 'old'}))
            self.assertIsNone(sequence_plan.held_manifest(folder, 'new'))
            self.assertEqual(sequence_plan.held_manifest(folder, 'old').name, 'moonray-sequence.json')

    def test_a_resumed_sequence_keeps_its_digits(self):
        with tempfile.TemporaryDirectory() as folder:
            sequence_plan.manifest_path(folder, 'frame').write_text(json.dumps({'signature': 's', 'first': 1, 'last': 2, 'step': 1, 'prefix': 'frame', 'fps': 24, 'motion_blur': False, 'digits': 4}))
            self.assertEqual(sequence_plan.plan(folder, 1, 2, 1, 'frame', 24, False, True, False, 's', 4)[0], [1, 2])
            with self.assertRaisesRegex(ValueError, 'digits'):
                sequence_plan.plan(folder, 1, 2, 1, 'frame', 24, False, True, False, 's', 6)


class Wiring(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1] / 'kit/MoonRayForModo/python/moonray_modo'

    def read(self, name):
        return (self.root / name).read_text(encoding='utf-8')

    def test_only_stills_and_animations_ask_for_xpu2(self):
        self.assertIn("snapshot['_xpu2_output']=True", self.read('animation.py'))
        self.assertIn('_xpu2_output=True', self.read('panel_tools.py'))
        self.assertNotIn('_xpu2_output', self.read('bake.py'))

    def test_what_only_moonray_writes_stays_moonrays(self):
        rule = self.read('render.py').split('def xpu2_output')[1].split('def binary_sessions')[0]
        for word in ("'deep'", "'recovery'", 'scalar_only', 'execution_mode'):
            self.assertIn(word, rule)

    def test_a_saved_picture_comes_from_the_denoised_render(self):
        self.assertIn("denoised if self.phase=='postdone' and denoised.is_file() else destination", self.read('render.py'))

    def test_a_sequence_gives_the_buttons_back_as_it_ends(self):
        self.assertIn('self.panel._set_rendering(False)', self.read('animation.py'))

    def test_xpu2_counts_deferred_samples_from_the_start_of_each_frame(self):
        source = (Path(__file__).resolve().parents[1] / 'xpu2/interactive/async_gpu.h').read_text(encoding='utf-8')
        start = source.index('memset32(state_->pointer, 0, sizeof(DeviceState) / 4);')
        self.assertIn('deferredHead_ = 0;', source[start - 400:start])

    def test_a_render_with_moonray_has_the_scenes_motion_blur(self):
        self.assertIn("still=self.preview_engine.currentData()=='moonray' and not self._following and not self.draft.isChecked() and self._motion_wanted()", self.read('panel.py'))

    def test_motion_blur_on_the_modo_camera_counts_everywhere(self):
        self.assertIn("channel(scene.renderCamera, 'motionBlur', 0)", self.read('host.py'))
        self.assertIn('if not self._motion_wanted():return self._capture()', self.read('panel.py'))
        self.assertIn("'motion': self._motion_wanted()", self.read('panel_tools.py'))

    def test_xpu2_realtime_blur_is_a_preference_off_by_default(self):
        self.assertIn("'xpu2_motion': (False, bool)", self.read('preferences.py'))
        panel = self.read('panel.py')
        self.assertIn('if not held and self._preview_blurred():', panel)
        self.assertIn("not self.ipr_mode.isChecked() or not self.preferences.get('xpu2_motion')", panel)

    def test_realtime_does_not_take_over_a_blurred_renders_reading(self):
        self.assertIn("if bool(scene.get('motion_steps'))!=self._preview_blurred():return None", self.read('panel.py'))


if __name__ == '__main__':
    unittest.main()
