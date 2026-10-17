import unittest
from xpu2.scene_lifecycle import EXPECTED,validate
class SceneLifecycleTests(unittest.TestCase):
    def evidence(self,case='replace'):
        d,a,n=EXPECTED[case]
        return dict(case=case,denied=d,accepted=a,destroyed=n,wrong_thread_destroy=0,job_retention=True,passed=True),dict(submitted=1,delivered=int(case!='cancel'),cancelled_requests=int(case=='cancel'),late_discarded=int(case=='cancel'),cancelled_before_dispatch=0,retained_async=0,worker_failures=0,worker_batches=1,max_batch_samples=8)
    def test_all_scenarios(self):
        for c in EXPECTED:self.assertEqual(validate(c,*self.evidence(c))['status'],'passed')
    def test_missing_cancellation_drain(self):
        c,q=self.evidence('cancel');q['late_discarded']=0
        with self.assertRaises(ValueError):validate('cancel',c,q)
    def test_early_scene_release(self):
        c,q=self.evidence();c['destroyed']=2
        with self.assertRaises(ValueError):validate('replace',c,q)
    def test_wrong_thread_cleanup(self):
        c,q=self.evidence();c['wrong_thread_destroy']=1
        with self.assertRaises(ValueError):validate('replace',c,q)
    def test_retained_gpu_work(self):
        c,q=self.evidence();q['retained_async']=1
        with self.assertRaises(ValueError):validate('replace',c,q)
    def test_no_gpu_work(self):
        c,q=self.evidence();q['max_batch_samples']=0
        with self.assertRaises(ValueError):validate('replace',c,q)
    def test_strict_counter_types(self):
        c,q=self.evidence();q['submitted']=True
        with self.assertRaises(ValueError):validate('replace',c,q)
    def test_dispatch_variant_preserves_resource_retention(self):
        from pathlib import Path
        from xpu2 import profile_patch,window_dispatch_patch
        root=Path(__file__).resolve().parents[1]/'xpu2'
        code=profile_patch.apply((root/'native_lambert_queue.cc').read_text(),(root/'batched_bridge.cc').read_text(),(root/'profile_metrics.h').read_text())
        code=window_dispatch_patch.apply(code)
        self.assertIn('revision,bool held=false,',code)
        self.assertIn('request->retainedResources=std::move(resources);',code)
        self.assertIn('request->retainedResources.reset();',code)
