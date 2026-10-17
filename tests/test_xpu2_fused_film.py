import unittest
from xpu2.fused_film_evidence import validate_fused,compare_fused

class FusedFilmTests(unittest.TestCase):
    def profile(self):
        p={k:0 for k in ('calls','eligible','accepted','replaced','cpu_skipped','unsupported','mismatch','errors','cleanup_errors','total_ns','initialization_ns','upload_ns','launch_ns','wait_ns','download_ns','compare_ns','fused_calls','shader_checked','shader_unsupported','shader_mismatch')}
        p.update(calls=2,eligible=16,accepted=16,replaced=16,cpu_skipped=16,fused_calls=2,shader_checked=16,packets=2,dispatches=2)
        return p
    def test_acceptance_requires_gpu_shader_validation(self):
        p=self.profile();self.assertEqual(validate_fused(p,'fast')['status'],'passed')
        p['shader_checked']=15
        with self.assertRaises(ValueError):validate_fused(p,'fast')
    def test_all_windows_must_use_fusion(self):
        p=self.profile();p['fused_calls']=1
        with self.assertRaises(ValueError):validate_fused(p,'fast')
    def test_corrupt_reference_must_fall_back_completely(self):
        p=self.profile();p.update(shader_mismatch=16,mismatch=16,accepted=0,replaced=0,cpu_skipped=0,shader_checked=0)
        self.assertEqual(validate_fused(p,'bad_shader')['rejected'],16)
        p['cpu_skipped']=1
        with self.assertRaises(ValueError):validate_fused(p,'bad_shader')
    def test_audit_must_retain_native_results(self):
        p=self.profile();p.update(replaced=0,cpu_skipped=0)
        self.assertEqual(validate_fused(p,'audit')['status'],'passed')
    def test_missing_ptx_is_not_shader_success(self):
        p=self.profile();p.update(errors=2,accepted=0,replaced=0,cpu_skipped=0,shader_checked=0)
        self.assertEqual(validate_fused(p,'missing')['status'],'passed')
    def test_same_work_required_for_comparison(self):
        p=self.profile();s=dict(p,fused_calls=0,shader_checked=0)
        self.assertEqual(compare_fused(s,p)['status'],'passed')
        p.update(eligible=15,accepted=15,replaced=15,cpu_skipped=15,shader_checked=15)
        with self.assertRaises(ValueError):compare_fused(s,p)
