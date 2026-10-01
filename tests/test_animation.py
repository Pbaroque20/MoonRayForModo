"""Deferred sequence recovery checks; run inside Modo's Python/Qt environment."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'kit/MoonRayForModo/python'))
try:
    from PySide2 import QtCore
    from moonray_modo import animation
except ImportError:
    QtCore=None


@unittest.skipIf(QtCore is None,'Requires the Modo Python/Qt environment')
class SequenceRecovery(unittest.TestCase):
    def setUp(self):
        class Renderer(QtCore.QObject):
            finished=QtCore.Signal(str)
            failed=QtCore.Signal(str)
            def stop(self): self.stopped=True
        class Status:
            def setText(self,text): self.text=text
        self.directory=tempfile.TemporaryDirectory()
        self.panel=QtCore.QObject()
        self.panel.renderer=Renderer(self.panel)
        self.panel.status=Status()
        self.sequence=animation.Sequence(self.panel,self.directory.name,1,2,24)
        with patch.object(self.sequence,'next_frame'):
            self.sequence.start()

    def tearDown(self):
        self.sequence.stop()
        self.directory.cleanup()

    def test_unrelated_output_cannot_advance_frame_number(self):
        self.sequence.expected_output=Path(self.directory.name)/'frame.000001.exr'
        self.sequence.finished(str(Path(self.directory.name)/'still.exr'))
        self.assertFalse(self.sequence.running)
        self.assertEqual(self.sequence.frame,1)
        self.assertEqual(self.sequence.completed,[])
        self.assertIsNone(animation.active)

    def test_manifest_failure_releases_sequence_and_preserves_completed_output(self):
        output=Path(self.directory.name)/'frame.000001.exr'
        output.write_bytes(b'completed fixture')
        self.sequence.expected_output=output.resolve()
        with patch.object(self.sequence,'write_manifest',side_effect=OSError('disk full')):
            self.sequence.finished(str(output))
        self.assertFalse(self.sequence.running)
        self.assertIsNone(animation.active)
        self.assertTrue(output.exists())
        self.assertEqual(self.sequence.completed,[{'frame':1,'file':str(output)}])
        self.assertIn('disk full',self.panel.status.text)


if __name__=='__main__': unittest.main()
