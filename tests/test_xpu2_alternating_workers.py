"""Reject incomplete/mismatched alternating-worker evidence."""
import importlib.util
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('alternating_probe', ROOT/'tools/xpu2_alternating_workers_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

class AlternatingEvidence(unittest.TestCase):
    def rows(self):
        return [dict(workers=w, samples_per_job=s, policy=p, repeat=r, digest='same',
                     wall_ns=100, cpu_busy_ns=10, gpu_busy_ns=0 if p=='cpu' else 20,
                     cpu_jobs=1024 if p=='cpu' else 512, gpu_jobs=0 if p=='cpu' else 512,
                     swaps=960 if p in ('barrier','alternating') else 0)
                for w in (1,6) for s in (8,128) for p in ('cpu','barrier','alternating','shared') for r in range(5)]
    def test_complete_evidence(self):
        self.assertEqual(len(probe.summarize(self.rows())),16)
    def test_missing_or_duplicate_trial(self):
        rows=self.rows()
        for bad in ([],rows[:-1],rows+[rows[0]],rows[:-1]+[rows[0]]):
            with self.assertRaises(ValueError):probe.summarize(bad)
    def test_different_results(self):
        rows=self.rows();rows[0]['digest']='changed'
        with self.assertRaises(ValueError):probe.summarize(rows)
    def test_cpu_control_must_not_use_gpu(self):
        rows=self.rows();rows[0].update(cpu_jobs=1023,gpu_jobs=1)
        with self.assertRaises(ValueError):probe.summarize(rows)
    def test_missing_work(self):
        rows=self.rows();rows[0]['cpu_jobs']=1023
        with self.assertRaises(ValueError):probe.summarize(rows)
    def test_alternation_counts(self):
        for updates in (dict(swaps=959),dict(cpu_jobs=511,gpu_jobs=513)):
            rows=self.rows();rows[5].update(updates)
            with self.assertRaises(ValueError):probe.summarize(rows)
    def test_impossible_durations(self):
        for updates in (dict(wall_ns=0),dict(cpu_busy_ns=101),dict(gpu_busy_ns=101),dict(cpu_busy_ns=-1)):
            rows=self.rows();rows[0].update(updates)
            with self.assertRaises(ValueError):probe.summarize(rows)
