import json
import unittest
from xpu2.shadow_requests import summarize
class ShadowRequestTests(unittest.TestCase):
    def row(self,**changes):
        row=dict(requests=8,rejected=0,stale_rejected=8,field_mismatches=0,gpu_mismatches=0,cpu_mismatches=0,cpu_reference_mismatches=0,blocked=3,lights=1)
        row.update(changes);return 'XPU2_SHADOW_REQUEST '+json.dumps(row)
    def test_counts(self):
        r=summarize(self.row()+'\n'+self.row());self.assertEqual(r['visible'],10);self.assertEqual(r['requests'],16)
    def test_missing(self):
        with self.assertRaises(ValueError):summarize('')
    def test_no_work(self):
        with self.assertRaises(ValueError):summarize(self.row(requests=0,stale_rejected=0,blocked=0))
    def test_stale(self):
        with self.assertRaises(ValueError):summarize(self.row(stale_rejected=7))
    def test_mismatches(self):
        for key in ('rejected','field_mismatches','gpu_mismatches','cpu_reference_mismatches'):
            with self.subTest(key=key),self.assertRaises(ValueError):summarize(self.row(**{key:1}))
    def test_invalid_counts(self):
        for change in ({'blocked':9},{'requests':-1},{'blocked':True},{'lights':0}):
            with self.subTest(change=change),self.assertRaises(ValueError):summarize(self.row(**change))
    def test_native_backend_disagreement_is_explicit(self):
        r=summarize(self.row(cpu_mismatches=1)+'\nXPU2_SHADOW_DISAGREEMENT '+json.dumps(dict(cpu=0,native_cpu=0,gpu=1,native_gpu=1)))
        self.assertEqual(r['status'],'passed');self.assertEqual(r['backend_parity'],'failed')
    def test_impossible_backend_count(self):
        with self.assertRaises(ValueError):summarize(self.row(cpu_mismatches=9))
    def test_backend_disagreement_requires_native_evidence(self):
        with self.assertRaises(ValueError):summarize(self.row(cpu_mismatches=1))
        with self.assertRaises(ValueError):summarize(self.row(cpu_mismatches=1)+'\nXPU2_SHADOW_DISAGREEMENT '+json.dumps(dict(cpu=0,native_cpu=1,gpu=1,native_gpu=1)))
