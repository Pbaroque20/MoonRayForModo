import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from prototype_wire import NativeProcess
from run_prototype import classify

class PrototypeGuards(unittest.TestCase):
    def test_failed_reference_gate_cannot_report_pass(self):
        report={'reference_repeatability':{'fixture':{'heldout_passed':True,'candidate_passed':False}}}
        classify(report)
        self.assertEqual(report['status'],'partial');self.assertEqual(report['operational_status'],'passed')
    def test_child_start_failure_releases_log(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'worker'
            with patch('prototype_wire.subprocess.Popen',side_effect=OSError('injected startup failure')):
                with self.assertRaises(OSError):NativeProcess('unused.exe',Path(root),'unused.ptx',folder)
            # Windows refuses deletion if this handle was leaked without sharing.
            (folder/'worker.log').unlink()
if __name__=='__main__':unittest.main()
