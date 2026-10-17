"""Reject unsafe bulk capacity patches and invalid local-worker evidence."""
import importlib.util
from pathlib import Path
import unittest
from xpu2 import local_batch_patch, profile_patch, window_dispatch_patch, async_transfer_patch, packed_readback_patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('local_batches_probe',ROOT/'tools/xpu2_local_batches_probe.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)

class BulkCapacity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        text=lambda name:(ROOT/'xpu2'/name).read_text()
        cls.code=packed_readback_patch.apply(async_transfer_patch.apply(window_dispatch_patch.apply(
            profile_patch.apply(text('native_lambert_queue.cc'),text('batched_bridge.cc'),text('profile_metrics.h')))))
    def test_matching_capacity_and_heap_scratch(self):
        for capacity in (512,8192,16384):
            code=local_batch_patch.apply(self.code,capacity)
            self.assertIn('if(count<1 || count>%d)'%capacity,code)
            self.assertIn('bulkResult=std::vector<U>(%d*9)'%capacity,code)
            self.assertNotIn('U lengths[512],result[512*9],returned[512*24];',code)
    def test_unsafe_capacity_rejected(self):
        for value in (0,511,513,16385,True,8192.0):
            with self.assertRaises(ValueError):local_batch_patch.apply(self.code,value)
    def test_anchor_drift_rejected(self):
        with self.assertRaises(ValueError):local_batch_patch.apply(self.code.replace('count>512','count>1024'))
        with self.assertRaises(ValueError):local_batch_patch.apply(local_batch_patch.apply(self.code))

class LocalEvidence(unittest.TestCase):
    def rows(self):
        cases=[(w,c,g,p,r) for w in (1,6) for c in (8,512)
               for p,g in [('cpu',128)]+[('shared',g) for g in (128,512,2048,8192,16384)] for r in range(3)]
        cases += [(6,512,g,'gpu',r) for g in (128,512,2048,8192,16384) for r in range(3)]
        return [dict(workers=w,cpu_chunk=c,gpu_chunk=g,policy=p,repeat=r,samples=262144,
                     cpu_samples=0 if p=='gpu' else 262144,gpu_samples=262144 if p=='gpu' else 0,
                     digest='same',wall_ns=100,claims=512) for w,c,g,p,r in cases]
    def test_complete(self):
        self.assertEqual(len(probe.summarize(self.rows())),29)
    def test_missing_duplicate_rejected(self):
        rows=self.rows()
        for bad in ([],rows[:-1],rows[:-1]+[rows[0]]):
            with self.assertRaises(ValueError):probe.summarize(bad)
    def test_changed_outputs_rejected(self):
        rows=self.rows();rows[0]['digest']='different'
        with self.assertRaises(ValueError):probe.summarize(rows)
    def test_bad_accounting_rejected(self):
        for update in (dict(samples=1),dict(cpu_samples=1),dict(wall_ns=0),dict(wall_ns=True),dict(claims=0),dict(gpu_samples=-1)):
            rows=self.rows();rows[0].update(update)
            with self.assertRaises(ValueError):probe.summarize(rows)
    def test_controls_must_not_mix_devices(self):
        rows=self.rows();rows[0].update(cpu_samples=262136,gpu_samples=8)
        with self.assertRaises(ValueError):probe.summarize(rows)
