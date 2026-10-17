import json
import unittest
from xpu2.native_scene_drain import validate
class NativeDrainTests(unittest.TestCase):
    def rows(self):
        events=['accelerator_rebuild','frame_open','captured','drain_begin','worker_done','drained','post_frame','context_teardown']
        return [dict(event=e,generation=0 if i==0 else 1,count=8,mismatches=0,blocked=1,error=0) for i,e in enumerate(events)]
    def check(self,rows):return validate('\n'.join('XPU2_NATIVE_DRAIN '+json.dumps(r) for r in rows),1)
    def test_valid_order(self):self.assertEqual(self.check(self.rows())['queries'],8)
    def test_native_difference_rejected(self):
        rows=self.rows();rows[4]['mismatches']=1
        with self.assertRaises(ValueError):self.check(rows)
    def test_cleanup_before_worker_rejected(self):
        rows=self.rows();rows[4],rows[6]=rows[6],rows[4]
        with self.assertRaises(ValueError):self.check(rows)
    def test_mutation_before_drain_rejected(self):
        rows=self.rows();rows.insert(3,dict(rows[-1],event='update_scene'))
        with self.assertRaises(ValueError):self.check(rows)
    def test_missing_native_work_rejected(self):
        rows=self.rows();rows[4]['count']=0
        with self.assertRaises(ValueError):self.check(rows)
    def test_reused_generation_rejected(self):
        rows=self.rows();rows.insert(2,dict(rows[1]))
        with self.assertRaises(ValueError):self.check(rows)
    def test_missing_teardown_rejected(self):
        with self.assertRaises(ValueError):self.check(self.rows()[:-1])
    def test_cancel_requires_real_gpu_and_no_completion(self):
        from unittest.mock import patch
        from xpu2.native_scene_drain import validate_cancel
        metrics=dict(xpu_selected=True,gpu_setup_complete=True,cpu_fallback=False,gpu_error=False)
        log='numRenderThreads:1\n@@MODO_SESSION CANCELED 0'
        lifetime=dict(status='passed',queries=8)
        with patch('xpu2.reference.log_metrics',return_value=metrics):
            self.assertTrue(validate_cancel(log,0,lifetime)['passed'])
            for text,code,proof in [(log,1,lifetime),(log+'\n@@MODO_SESSION DONE 0',0,lifetime),(log,0,dict(status='passed',queries=0)),(log.replace('Threads:1','Threads:2'),0,lifetime)]:
                with self.assertRaises(ValueError):validate_cancel(text,code,proof)
