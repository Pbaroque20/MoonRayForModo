import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch
from fallback import FallbackJob,environment,execution
from protocol_model import Epoch
from reference_runtime import inventory,identity,verify


LOG="executing an xpu render\nGPU: Setup complete\nGPU bundled intersection ray utilization = 98.5%\n"
STATS="Thread(s),12\n"


class FallbackContracts(unittest.TestCase):
    def test_strict_mode_requires_actual_device_work_and_threads(self):
        self.assertTrue(execution(LOG,STATS,12)["passed"])
        for log,stats in ((LOG+"falling back to vectorized",STATS),
                          (LOG.replace("98.5","0"),STATS),
                          (LOG+"optixLaunch() failure",STATS),
                          (LOG,"Thread(s),1\n"),("requested xpu only",STATS)):
            self.assertFalse(execution(log,stats,12)["passed"])

    def test_environment_does_not_inherit_experiment_or_display_switches(self):
        with patch.dict(os.environ,{"XPU2_GPU_NOWAIT":"1","XPU_PLUS_SHADE_PRESENCE_SKIP":"1",
                                    "OCIO":"private.ocio","RDL2_DSO_PATH":"foreign"}):
            env=environment(Path("runtime"),Path("temporary"))
        self.assertFalse(any(k.startswith(("XPU2_","XPU_PLUS_")) for k in env))
        self.assertNotIn("OCIO",env)
        self.assertNotEqual(env["RDL2_DSO_PATH"],"foreign")

    def test_polling_and_cancellation_never_wait_or_expose_partial_output(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            scene=root/"scene.rdlb";scene.write_bytes(b"fixture")
            proc=Mock()
            proc.poll.return_value=None
            with patch("fallback.subprocess.Popen",return_value=proc):
                job=FallbackJob(root,scene,root/"run",12,Epoch(1,1,1,1))
                job.start()
                job.image.write_bytes(b"partial")
                self.assertEqual(job.poll(),"running")
                self.assertIsNone(job.result(job.epoch))
                job.cancel()
                proc.terminate.assert_called_once()
                proc.poll.return_value=0  # Even success racing with cancel is rejected.
                self.assertEqual(job.poll(),"cancelled")
                self.assertIsNone(job.result(job.epoch))
                proc.wait.assert_not_called()

    def test_finished_result_rejects_settings_or_session_staleness(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            scene=root/"scene.rdlb";scene.write_bytes(b"fixture")
            proc=Mock()
            proc.poll.return_value=0
            with patch("fallback.subprocess.Popen",return_value=proc):
                job=FallbackJob(root,scene,root/"run",12,Epoch(1,1,1,1))
                job.start()
                job.poll()
                job.image.write_bytes(b"validated by decoder outside this model")
                (job.output/"render.log").write_text(LOG)
                (job.output/"stats.csv").write_text(STATS)
                self.assertEqual(job.result(job.epoch).tier,"F")
                self.assertIsNone(job.result(Epoch(1,1,1,2)))
                self.assertIsNone(job.result(Epoch(2,1,1,1)))
                proc.wait.assert_not_called()

    def test_timeout_cancels_only_owned_process(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);scene=root/"scene.rdlb";scene.write_bytes(b"fixture")
            proc=Mock();proc.poll.return_value=None
            with patch("fallback.subprocess.Popen",return_value=proc):
                job=FallbackJob(root,scene,root/"run",1,Epoch(1,1,1,1),timeout=.1)
                job.start()
                job.began-=1
                self.assertEqual(job.poll(),"cancelling")
                self.assertEqual(job.reason,"timeout")
                proc.poll.return_value=-1
                self.assertEqual(job.poll(),"cancelled")
                proc.wait.assert_not_called()

    def test_inventory_detects_changed_added_and_removed_files(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);file=root/"payload.dll";file.write_bytes(b"one")
            contract={"files":inventory(root)}
            lock={"identity":identity(contract),"contract":contract}
            verify(root,lock)
            file.write_bytes(b"two")
            with self.assertRaises(ValueError):verify(root,lock)
            file.write_bytes(b"one");extra=root/"new.ptx";extra.write_bytes(b"new")
            with self.assertRaises(ValueError):verify(root,lock)
            extra.unlink();file.unlink()
            with self.assertRaises(ValueError):verify(root,lock)


if __name__=="__main__":
    unittest.main(verbosity=2)
