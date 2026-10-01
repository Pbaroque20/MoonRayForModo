# python
"""Deferred Qt lifecycle regressions, including repeated stop/restart and timeout."""
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import lx
from PySide2 import QtCore

root=Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
assert lx.service.Platform().IsHeadless()
assert lx.eval('query platformservice appversion ?')==1619
sys.path.insert(0,str(root/'tests'))
import test_render
from moonray_modo.render import Renderer

class Recovery(unittest.TestCase):
    def test_repeated_stop_is_safe_and_close_rejects_submission(self):
        renderer=Renderer()
        try:
            for _ in range(100): renderer.stop()
            renderer.close(); renderer.close()
            with self.assertRaises(ValueError):
                renderer.submit({},'',128,128,1,0,1)
        finally:
            renderer.close()

    def test_timeout_cancels_without_publishing_a_frame(self):
        renderer=Renderer()
        failures=[];images=[]
        renderer.failed.connect(failures.append)
        renderer.image_ready.connect(images.append)
        try:
            renderer._timed_out()
            self.assertTrue(renderer.canceled)
            self.assertEqual(len(failures),1)
            self.assertFalse(images)
            self.assertFalse(renderer.watchdog.isActive())
        finally:
            renderer.close()

suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromModule(test_render),
                         unittest.defaultTestLoader.loadTestsFromTestCase(Recovery)])
log=io.StringIO();result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
folder=root/'test-results/cpu-features';folder.mkdir(parents=True,exist_ok=True)
(folder/'reliability.json').write_text(json.dumps({'passed':result.wasSuccessful(),'tests':result.testsRun,
    'level':'Qt lifecycle; large-scene load/memory testing still required','log':log.getvalue()},indent=2))
if not result.wasSuccessful(): raise RuntimeError(log.getvalue())
