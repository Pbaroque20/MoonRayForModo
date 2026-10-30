"""A render started by hand gives XPU2 another try after it left the session to MoonRay XPU (persistent.retry_xpu2)."""
import unittest
from types import SimpleNamespace
from test_bucket_settings import persistent_session
from moonray_modo import native


class XPU2Retry(unittest.TestCase):
    def state(self, refused):
        calls = []
        state = SimpleNamespace(running=lambda: True, signature=('runtime', 0, 'auto', 0) + native.source_switches(),
                                stopping=False, sent=None, xpu2_refused=refused,
                                process=SimpleNamespace(kill=lambda: calls.append('restart')),
                                _dispatch=lambda: calls.append('dispatch'), idle=SimpleNamespace(cancel=lambda: None))
        return state, calls

    def test_a_render_by_hand_restarts_a_session_xpu2_left(self):
        Session = persistent_session()
        state, calls = self.state('ended unexpectedly')
        Session.retry_xpu2(state)
        Session.submit(state, 'scene', 'runtime', 0, 'auto', 1, 0)
        self.assertEqual(calls, ['restart'])
        self.assertIsNone(state.xpu2_refused)
        # Asked once: the next update goes to the session started again, as any other.
        state.stopping = False
        Session.submit(state, 'scene', 'runtime', 0, 'auto', 2, 0)
        self.assertEqual(calls, ['restart', 'dispatch'])

    def test_without_a_refusal_nothing_starts_again(self):
        Session = persistent_session()
        state, calls = self.state(None)
        Session.retry_xpu2(state)
        Session.submit(state, 'scene', 'runtime', 0, 'auto', 1, 0)
        self.assertEqual(calls, ['dispatch'])

    def test_an_update_not_by_hand_keeps_the_refusal(self):
        Session = persistent_session()
        state, calls = self.state('it does not render this scene')
        Session.submit(state, 'scene', 'runtime', 0, 'auto', 1, 0)
        self.assertEqual(calls, ['dispatch'])
        self.assertEqual(state.xpu2_refused, 'it does not render this scene')


if __name__ == '__main__':
    unittest.main()
