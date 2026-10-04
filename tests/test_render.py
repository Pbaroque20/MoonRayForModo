"""Lifecycle tests run inside Modo's Qt runtime by the host probe."""
import pathlib
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
try:
    from PySide2 import QtCore
    from moonray_modo.render import Renderer
except ImportError:
    QtCore = None


@unittest.skipIf(QtCore is None, 'Run inside Modo for the Qt lifecycle tests')
class HostMapTests(unittest.TestCase):
    def test_missing_corner_does_not_export_unwritten_storage(self):
        from moonray_modo import host
        class Polygon:
            def VertexByIndex(self, index): return index
            def MapEvaluate(self, map_id, point, storage):
                if point==0:
                    storage.set((.25,.75))
                    return True
                return False
        self.assertEqual(host.corner_values(Polygon(),123,3,2),[])

    def test_valid_zero_uv_is_preserved(self):
        from moonray_modo import host
        class Polygon:
            def VertexByIndex(self, index): return index
            def MapEvaluate(self, map_id, point, storage):
                storage.set((0.0,0.0))
                return True
        self.assertEqual(host.corner_values(Polygon(),123,3,2),[[0.0,0.0]]*3)


@unittest.skipIf(QtCore is None, 'Run inside Modo for the Qt lifecycle tests')
class NativePreviewStatusTests(unittest.TestCase):
    def test_frame_queued_before_pause_is_discarded_without_error(self):
        from moonray_modo.native_preview import Controller
        session={'renderer':SimpleNamespace(passes=[]),'pending_frame':'old.exr','pending_since':1}
        controller=SimpleNamespace(closed=False,bridge=SimpleNamespace(MR_preview_publish=lambda *args:0),
                                   sessions={1:session},errors={})
        Controller.publish(controller,1,'old.exr')
        self.assertFalse(controller.errors)
        self.assertNotIn('pending_frame',session)
        self.assertNotIn('pending_since',session)

    def test_queued_image_from_old_generation_is_not_published(self):
        from moonray_modo.native_preview import Controller
        pending={}; published=[]
        renderer=SimpleNamespace(generation=1)
        controller=SimpleNamespace(closed=False,sessions={1:{'renderer':renderer}},
            idle=SimpleNamespace(submit=lambda key,callback:pending.update({key:callback})),
            publish=lambda *args:published.append(args))
        Controller.queue_frame(controller,1,'old.exr')
        renderer.generation=2
        pending[('frame',1)]()
        self.assertFalse(published)

    def test_pending_buffer_reports_failure_and_recovers_only_after_transfer(self):
        from moonray_modo.native_preview import Controller
        statuses=[]
        bridge=SimpleNamespace(MR_preview_publish=lambda *args:-2,
                               MR_preview_diagnostic=lambda *args:b'WriteBegin=0x80000000')
        session={'renderer':SimpleNamespace(passes=[])}
        controller=SimpleNamespace(closed=False,bridge=bridge,sessions={1:session},errors={},
                                   status=lambda identity,text:statuses.append(text))
        with patch('moonray_modo.native_preview.time.monotonic',return_value=100):
            Controller.publish(controller,1,'frame.exr')
        self.assertNotIn(1,controller.errors)
        self.assertEqual(session['pending_frame'],'frame.exr')
        with patch('moonray_modo.native_preview.time.monotonic',return_value=111):
            Controller.publish(controller,1,'frame.exr')
        self.assertIn('WriteBegin=0x80000000',controller.errors[1])
        self.assertNotIn('Preview complete',statuses)
        bridge.MR_preview_publish=lambda *args:1
        Controller.publish(controller,1,'frame.exr')
        self.assertFalse(controller.errors)
        self.assertNotIn('pending_frame',session)
        self.assertNotIn('pending_since',session)
        self.assertEqual(statuses[-1],'Preview complete')


@unittest.skipIf(QtCore is None, 'Run inside Modo for the Qt lifecycle tests')
class IdleLifecycleTests(unittest.TestCase):
    def test_latest_frame_wins_and_close_cancels_exact_visitor(self):
        from moonray_modo import idle
        from unittest.mock import Mock
        platform=Mock(); visitor=object(); received=[]
        with patch.object(idle.lx.service,'Platform',return_value=platform), patch.object(idle.lx.object,'Visitor',return_value=visitor):
            dispatcher=idle.Dispatcher()
        dispatcher.submit('frame',lambda:received.append('old'))
        dispatcher.submit('frame',lambda:received.append('new'))
        platform.DoWhenUserIsIdle.assert_called_once_with(visitor,idle.FLAGS)
        dispatcher.vis_Evaluate()
        self.assertEqual(received,['new'])
        dispatcher.submit('frame',lambda:received.append('closed'))
        dispatcher.close()
        platform.CancelDoWhenUserIsIdle.assert_called_once_with(visitor,idle.FLAGS)
        dispatcher.vis_Evaluate()
        self.assertEqual(received,['new'])

    def test_timer_stopped_inside_callback_is_not_rearmed(self):
        from moonray_modo import idle
        from unittest.mock import Mock
        platform=Mock(); visitor=object()
        with patch.object(idle.lx.service,'Platform',return_value=platform), patch.object(idle.lx.object,'Visitor',return_value=visitor):
            timer=idle.Timer(lambda:timer.stop(),20)
        timer.start()
        timer.vis_Evaluate()
        self.assertFalse(timer.active)
        platform.TimerStart.assert_called_once_with(visitor,20,idle.FLAGS)


@unittest.skipIf(QtCore is None, 'Run inside Modo for the Qt lifecycle tests')
class RenderTests(unittest.TestCase):
    def setUp(self):
        self.app = QtCore.QCoreApplication.instance() or QtCore.QCoreApplication([])
        self.renderer = Renderer()
        self.renderer.active = {'output': None, 'generation': 3, 'snapshot':{}, 'runtime':''}
        # Model a pass after _begin_pass initialized its completion bookkeeping.
        self.renderer.original_published=False
        self.renderer.gpu_error=False
        self.renderer.post_jobs=[]
        self.renderer.preview_files={}
        self.renderer.buffer_path=pathlib.Path(self.renderer.directory.name)/'buffer.exr'
        self.renderer.passes = []
        self.renderer.image_path = pathlib.Path(self.renderer.directory.name) / 'render.png'
        self.errors, self.images = [], []
        self.renderer.failed.connect(self.errors.append)
        self.renderer.image_ready.connect(self.images.append)

    def tearDown(self):
        self.renderer.close()

    def test_crash_never_publishes_partial_output(self):
        self.renderer.image_path.write_bytes(b'partial' * 10)
        self.renderer._exited(0xC000001D, QtCore.QProcess.CrashExit)
        self.assertFalse(self.images)
        self.assertIn('unsupported CPU instruction', self.errors[0])

    def test_zero_byte_output_is_not_success(self):
        self.renderer.image_path.touch()
        self.renderer._exited(0, QtCore.QProcess.NormalExit)
        self.assertTrue(self.errors)
        self.assertFalse(self.images)

    def test_stop_discards_late_completion(self):
        self.renderer.image_path.write_bytes(b'not_a_real_image' * 3)
        self.renderer.stop()
        self.renderer._exited(0, QtCore.QProcess.NormalExit)
        self.assertFalse(self.images)
        self.assertFalse(self.errors)

    def test_stale_refinement_callback_does_not_start(self):
        self.renderer._begin_pass(2)
        self.assertEqual(self.renderer.process.state(), QtCore.QProcess.NotRunning)

    def test_failed_render_preserves_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            final = pathlib.Path(directory) / 'final.exr'
            final.write_bytes(b'previous render')
            self.renderer.active['output'] = str(final)
            self.renderer._exited(1, QtCore.QProcess.NormalExit)
            self.assertEqual(final.read_bytes(), b'previous render')

    def test_final_copy_failure_is_reported(self):
        self.renderer.image_path.write_bytes(b'not_a_real_image' * 3)
        self.renderer.active['output'] = str(pathlib.Path(self.renderer.directory.name) / 'missing' / 'final.exr')
        self.renderer._exited(0, QtCore.QProcess.NormalExit)
        self.assertIn('Cannot save render', self.errors[0])
