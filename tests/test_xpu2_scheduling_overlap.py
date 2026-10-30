"""Do not accept incomplete or unequal scheduling measurements as speedup evidence."""
import copy
import importlib.util
from pathlib import Path
import unittest
ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scheduling_probe', ROOT/'tools/xpu2_scheduling_probe.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class SchedulingEvidence(unittest.TestCase):
    def rows(self):
        return [dict(schedule=s, steps=128, repeat=0, rounds=4, wall_ns=t,
                     cpu_ns=20, collect_ns=20, cpu_started_pending=p,
                     cpu_finished_pending=p, digest='same')
                for s, t, p in [('serial', 100, 0), ('overlap', 50, 4)]]

    def test_matched_measurements(self):
        self.assertEqual(probe.summarize(self.rows())[0]['speedup'], 2)

    def test_missing_work_and_duplicate_repeats_rejected(self):
        rows = self.rows()
        for invalid in ([], rows[:1], rows + copy.deepcopy(rows)):
            with self.assertRaises(ValueError):
                probe.summarize(invalid)
        rows[1]['rounds'] = 8
        with self.assertRaises(ValueError):
            probe.summarize(rows)

    def test_nonidentical_results_rejected(self):
        rows = self.rows()
        rows[1]['digest'] = 'different'
        with self.assertRaises(ValueError):
            probe.summarize(rows)

    def test_invalid_timings_and_overlap_rejected(self):
        for key, value in [('wall_ns', 0), ('wall_ns', True), ('cpu_ns', -1),
                           ('collect_ns', 101), ('cpu_started_pending', 5),
                           ('cpu_finished_pending', 1)]:
            rows = self.rows()
            rows[0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                probe.summarize(rows)
