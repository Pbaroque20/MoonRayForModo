import unittest
from xpu2.film_evidence import validate_profile

class FilmEvidenceTests(unittest.TestCase):
    def profile(self):
        p={k:0 for k in ('calls','eligible','accepted','replaced','cpu_skipped','unsupported','mismatch','errors','cleanup_errors','total_ns','initialization_ns','upload_ns','launch_ns','wait_ns','download_ns','compare_ns')}
        p.update(calls=3,eligible=20,accepted=20,replaced=20,cpu_skipped=20,total_ns=100,upload_ns=10,wait_ns=20)
        return p
    def test_fast_requires_real_replacement(self):
        self.assertEqual(validate_profile(self.profile(),'fast')['cpu_contribution_skipped'],20)
        p=self.profile();p['cpu_skipped']=0
        with self.assertRaises(ValueError):validate_profile(p,'fast')
    def test_audit_cannot_replace(self):
        p=self.profile();p.update(replaced=0,cpu_skipped=0)
        self.assertEqual(validate_profile(p,'audit')['status'],'passed')
        p['replaced']=1
        with self.assertRaises(ValueError):validate_profile(p,'audit')
    def test_mismatch_rejected(self):
        p=self.profile();p['mismatch']=1
        with self.assertRaises(ValueError):validate_profile(p,'fast')
    def test_partial_acceptance_rejected(self):
        p=self.profile();p['accepted']=19
        with self.assertRaises(ValueError):validate_profile(p,'fast')
    def test_cleanup_failure_rejected(self):
        p=self.profile();p['cleanup_errors']=1
        with self.assertRaises(ValueError):validate_profile(p,'fast')
    def test_missing_ptx_requires_cpu_fallback(self):
        p=self.profile();p.update(errors=3,accepted=0,replaced=0,cpu_skipped=0)
        self.assertEqual(validate_profile(p,'missing')['status'],'passed')
        p['accepted']=1
        with self.assertRaises(ValueError):validate_profile(p,'missing')
    def test_no_work_cannot_pass(self):
        p=self.profile();p['eligible']=0
        with self.assertRaises(ValueError):validate_profile(p,'fast')
    def test_missing_metrics_rejected(self):
        p=self.profile();del p['upload_ns']
        with self.assertRaises(ValueError):validate_profile(p,'fast')
    def test_overlapping_timing_totals_rejected(self):
        p=self.profile();p['upload_ns']=100
        with self.assertRaises(ValueError):validate_profile(p,'fast')
