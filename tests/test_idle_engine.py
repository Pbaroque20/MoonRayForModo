"""A preview stopped by hand keeps MoonRay or XPU2 loaded and idle (persistent.Session.pause): the frame now going is
drained, nothing newer is sent, and the process, its scene and its GPU structures wait for the next preview; it is let
go when its scene closes (Session.release), told to quit so that it ends as it would of itself, killed only if it has
not within its grace."""
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock
from test_bucket_settings import persistent_session


class Pause(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.Session = persistent_session()
        self.calls = []

    def state(self, applied=None, sent=None, latest=None, idle=None, running=True):
        return SimpleNamespace(running=lambda: running, stopping=False, closed=False, applied=applied, sent=sent,
                               latest=latest, idle=SimpleNamespace(since=idle, cancel=lambda: None), root=pathlib.Path(self.folder.name),
                               process=SimpleNamespace(kill=lambda: self.calls.append('kill')))

    def pause(self, state, drains=True):
        with mock.patch.dict(self.Session.pause.__globals__, {'drains': lambda runtime: drains}):
            return self.Session.pause(state)

    def drained(self):
        held = pathlib.Path(self.folder.name) / 'drain.txt'
        return held.read_text(encoding='ascii') if held.is_file() else None

    def test_a_frame_rendering_is_drained_and_the_process_kept(self):
        frame = {'id': 7, 'runtime': 'rt'}
        state = self.state(applied=frame, latest=frame)
        self.assertTrue(self.pause(state))
        self.assertEqual(self.drained(), '7')
        self.assertEqual(self.calls, [])
        self.assertIs(state.latest, frame)

    def test_a_scene_on_its_way_is_let_arrive_and_nothing_newer_sent(self):
        applied, sent, newer = {'id': 7, 'runtime': 'rt'}, {'id': 8, 'runtime': 'rt'}, {'id': 9, 'runtime': 'rt'}
        state = self.state(applied=applied, sent=sent, latest=newer)
        self.assertTrue(self.pause(state))
        # The scene sent is the frame drained, and the latest: once it is applied, _dispatch has nothing to send.
        self.assertEqual(self.drained(), '8')
        self.assertIs(state.latest, sent)

    def test_an_idle_process_is_kept_as_it_is(self):
        frame = {'id': 7, 'runtime': 'rt'}
        state = self.state(applied=frame, latest=frame, idle=123.0)
        self.assertTrue(self.pause(state))
        self.assertIsNone(self.drained())

    def test_ended_as_before_where_it_cannot_be_kept(self):
        frame = {'id': 7, 'runtime': 'rt'}
        # A runtime that cannot drain; a scene waiting to be compared on a thread; no process; nothing applied.
        self.assertFalse(self.pause(self.state(applied=frame, latest=frame), drains=False))
        self.assertFalse(self.pause(self.state(applied=frame, latest={'id': 9, 'runtime': 'rt'})))
        self.assertFalse(self.pause(self.state(applied=frame, latest=frame, running=False)))
        self.assertFalse(self.pause(self.state()))


class Release(unittest.TestCase):
    def test_told_to_quit_and_killed_only_after_its_grace(self):
        Session = persistent_session()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        calls, timers = [], []
        state = SimpleNamespace(running=lambda: True, idle=SimpleNamespace(cancel=lambda: calls.append('cancel')),
                                xpu2_refused='x', latest={'id': 1}, sent=None, applied={'id': 1}, stopping=False,
                                command_channel=None, root=pathlib.Path(folder.name),
                                process=SimpleNamespace(kill=lambda: calls.append('kill'), state=lambda: 1))
        timer = SimpleNamespace(singleShot=lambda ms, slot: timers.append((ms, slot)))
        with mock.patch.dict(Session.release.__globals__, {'QtCore': SimpleNamespace(QTimer=timer, QProcess=SimpleNamespace(NotRunning=0))}):
            Session.release(state, 10000)
        self.assertEqual((pathlib.Path(folder.name) / 'command.txt').read_text(encoding='utf-8'), '0\nquit\n\n\n')
        self.assertTrue(state.stopping)
        self.assertIsNone(state.latest)
        self.assertNotIn('kill', calls)
        # Still running past its grace: ended outright.
        self.assertEqual(timers[0][0], 10000)
        timers[0][1]()
        self.assertIn('kill', calls)


if __name__ == '__main__':
    unittest.main()
