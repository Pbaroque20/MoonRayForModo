"""Prepared deltas are used only against their exact acknowledged base."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from test_bucket_settings import persistent_session

class PreparedSceneTests(unittest.TestCase):
    def check_dispatch(self, same_base, limit=None):
        Session = persistent_session()
        base = {'id': 1, 'text': 'old'}
        prepared = {'base': base, 'delta': 'edit', 'full_bytes': b'full', 'delta_bytes': b'edit'}
        request = {'id': 3, 'text': 'full', 'prepared': prepared}
        writes = []
        def write(request, suffix, text, payload=None):
            writes.append((suffix, text, payload))
            return 'modo-memory:' + suffix
        from pathlib import Path
        state = SimpleNamespace(latest=request, applied=base if same_base else {'id': 2, 'text': 'other'},
            _write_scene=write, root=Path('.'), scene_memory=True, command_channel=Mock(), status=Mock())
        held = dict(difference=Mock(side_effect=AssertionError('main-thread diff')), **({'DIFF_HERE': limit} if limit is not None else {}))
        with patch.dict(Session._dispatch.__globals__, **held):
            Session._dispatch(state)
        self.assertIs(state.sent, request)
        self.assertEqual(writes[0], ('full', 'full', b'full'))
        command = state.command_channel.send.call_args[0][0]
        if same_base:
            self.assertEqual(writes[1], ('delta', 'edit', b'edit'))
            self.assertIn('\ndelta\n', command)
        else:
            self.assertEqual(len(writes), 1)
            self.assertIn('\nfull\n', command)

    def test_matching_base_uses_worker_delta(self):
        self.check_dispatch(True)

    def test_stale_base_with_a_large_scene_uses_full_scene_without_main_thread_diff(self):
        self.check_dispatch(False, limit=2)

    def test_stale_base_with_a_small_scene_makes_the_delta_again(self):
        # A drag of the camera: the writer's delta was made against a scene since replaced; the one applied is diffed
        # again on Modo's thread, the text being small, and goes as a delta, not a reload.
        Session = persistent_session()
        applied = {'id': 2, 'text': 'other'}
        request = {'id': 3, 'text': 'full', 'prepared': {'base': {'id': 1, 'text': 'old'}, 'delta': 'edit', 'full_bytes': b'full', 'delta_bytes': b'edit'}}
        writes = []
        def write(request, suffix, text, payload=None):
            writes.append((suffix, text, payload))
            return 'modo-memory:' + suffix
        from pathlib import Path
        state = SimpleNamespace(latest=request, applied=applied, _write_scene=write, root=Path('.'), scene_memory=True,
                                command_channel=Mock(), status=Mock())
        with patch.dict(Session._dispatch.__globals__, difference=Mock(return_value='again')) as held:
            Session._dispatch(state)
            held['difference'].assert_called_once_with('other', 'full')
        self.assertEqual(writes[1], ('delta', 'again', None))
        self.assertIn('\ndelta\n', state.command_channel.send.call_args[0][0])

class SceneWriterHostTests(unittest.TestCase):
    def test_writer_prepares_utf8_and_delta_off_caller(self):
        try:
            from moonray_modo.render import SceneWriter
        except ImportError:
            self.skipTest('Requires Modo Qt')
        import tempfile
        from pathlib import Path
        from moonray_modo import rdla, scene_delta
        base = {'id': 1, 'text': 'old'}
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'scene.rdla'
            worker = SceneWriter((), path, (), 2, applied=base)
            with patch.object(rdla, 'scene_text', return_value='new scene'), patch.object(scene_delta, 'difference', return_value='edit') as difference:
                worker.start()
                self.assertTrue(worker.wait(5000))
            self.assertEqual(worker.outcome, ('new scene', ''))
            self.assertIs(worker.prepared['base'], base)
            self.assertEqual(worker.prepared['delta_bytes'], b'edit')
            self.assertEqual(path.read_bytes(), b'new scene')
            difference.assert_called_once_with('old', 'new scene')
            worker.deleteLater()

if __name__ == '__main__':
    unittest.main()
