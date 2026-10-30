import unittest
from xpu2.streamed_film_evidence import validate_streamed,compare_streamed

class StreamedFilmTests(unittest.TestCase):
    def profile(self):
        p={k:0 for k in ('calls','eligible','accepted','replaced','cpu_skipped','unsupported','mismatch','errors','cleanup_errors','total_ns','initialization_ns','upload_ns','launch_ns','wait_ns','download_ns','compare_ns','fused_calls','shader_checked','shader_unsupported','shader_mismatch','async_enabled','pinned_allocations','pinned_frees','async_batches','async_completed','completion_waits','error_drains','staging_ns')}
        p.update(calls=2,eligible=16,accepted=16,replaced=16,cpu_skipped=16,fused_calls=2,shader_checked=16,packets=2,dispatches=2,async_enabled=1,pinned_allocations=2,pinned_frees=2,async_batches=2,async_completed=2,completion_waits=2)
        return p
    def test_reads_require_completion(self):
        p=self.profile();self.assertEqual(validate_streamed(p,'fast')['status'],'passed')
        p['async_completed']=1
        with self.assertRaises(ValueError):validate_streamed(p,'fast')
    def test_extra_wait_rejected(self):
        p=self.profile();p['completion_waits']=4
        with self.assertRaises(ValueError):validate_streamed(p,'fast')
    def test_pinned_leak_rejected(self):
        p=self.profile();p['pinned_frees']=1
        with self.assertRaises(ValueError):validate_streamed(p,'fast')
    def fault(self):
        p=self.profile();p.update(accepted=0,replaced=0,cpu_skipped=0,shader_checked=0,errors=2,dispatches=0,async_completed=0,completion_waits=0)
        return p
    def test_queued_failure_requires_drain(self):
        p=self.fault();p['error_drains']=2
        self.assertEqual(validate_streamed(p,'transfer_fault')['status'],'passed')
        p['error_drains']=1
        with self.assertRaises(ValueError):validate_streamed(p,'transfer_fault')
    def test_partial_allocation_must_be_freed(self):
        p=self.fault();p.update(async_batches=0,pinned_allocations=1,pinned_frees=1)
        self.assertEqual(validate_streamed(p,'pinned_fault')['status'],'passed')
        p['pinned_allocations']=p['pinned_frees']=0
        with self.assertRaises(ValueError):validate_streamed(p,'pinned_fault')
    def test_comparison_requires_same_work(self):
        p=self.profile();b=dict(p,async_enabled=0,pinned_allocations=0,pinned_frees=0,async_batches=0,async_completed=0,completion_waits=0)
        self.assertEqual(compare_streamed(b,p)['status'],'passed')
        p.update(eligible=15,accepted=15,replaced=15,cpu_skipped=15,shader_checked=15)
        with self.assertRaises(ValueError):compare_streamed(b,p)
