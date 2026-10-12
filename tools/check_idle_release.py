"""Standalone lifecycle checks, without Modo, Qt, a GPU or renderer processes. Not run automatically."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

class Signal:
    def connect(self, callback): self.callback=callback
class Object:
    def __init__(self, parent=None): pass
class Timer:
    def __init__(self, parent): self.timeout=Signal();self.active=False
    def setInterval(self, value): self.interval=value
    def start(self): self.active=True
    def stop(self): self.active=False
qt=types.ModuleType('PySide2');qt.QtCore=types.SimpleNamespace(QObject=Object,QTimer=Timer)
sys.modules['PySide2']=qt
package=types.ModuleType('moonray_modo');package.__path__=[];sys.modules['moonray_modo']=package
preferences=types.ModuleType('moonray_modo.preferences')
class Preferences:
    minutes=5
    def get(self, key): return self.minutes
preferences.Preferences=Preferences;sys.modules['moonray_modo.preferences']=preferences
path=Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python/moonray_modo/idle_release.py'
spec=importlib.util.spec_from_file_location('moonray_modo.idle_release',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class IdleTests(unittest.TestCase):
    def setUp(self):
        Preferences.minutes=5;self.calls=[];self.available=True;self.now=100.
        self.clock=patch.object(module.time,'monotonic',lambda:self.now);self.clock.start();self.addCleanup(self.clock.stop)
        self.idle=module.IdleRelease(None,lambda:self.calls.append('released'),lambda:self.available)
    def test_only_completed_sessions_are_released(self):
        self.assertFalse(self.idle.release_now());self.idle.arm();self.now+=299;self.idle._tick()
        self.assertEqual(self.calls,[]);self.now+=1;self.idle._tick();self.assertEqual(self.calls,['released'])
    def test_new_submission_cancels_expiry(self):
        self.idle.arm();self.idle.cancel();self.now+=600;self.idle._tick();self.assertEqual(self.calls,[])
    def test_completion_handler_can_submit_again(self):
        self.idle.arm();self.idle.cancel() # completion signal causes another pass
        self.assertIsNone(self.idle.since);self.assertFalse(self.idle.timer.active)
    def test_never_setting_still_allows_manual_release(self):
        Preferences.minutes=0;self.idle.arm();self.now+=100000;self.idle._tick();self.assertEqual(self.calls,[])
        self.assertTrue(self.idle.release_now());self.assertFalse(self.idle.release_now())
    def test_inflight_work_cannot_be_killed(self):
        self.idle.arm();self.available=False;self.now+=600;self.idle._tick()
        self.assertFalse(self.idle.release_now());self.assertEqual(self.calls,[])
        self.available=True;self.idle._tick();self.assertEqual(self.calls,['released'])
    def test_preference_change_while_idle(self):
        Preferences.minutes=0;self.idle.arm();self.now+=65;Preferences.minutes=1
        self.idle._tick();self.assertEqual(self.calls,['released'])

if __name__=='__main__':unittest.main()
