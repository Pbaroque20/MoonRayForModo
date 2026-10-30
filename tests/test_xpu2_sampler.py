import gzip
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from xpu2.sampler import UNKNOWN, FIELDS, MODES, read, compare, matches_reference, compare_handoffs


def corpus():
    records = []
    for i, key in enumerate(itertools.product((1, 2, 3), (0, 2, 3), (False, True),
                                              (UNKNOWN, 1, 16, 64), (0, 19, UNKNOWN), (0, 1, 2))):
        row = dict(zip(FIELDS, key))
        count = (65 if row["total"] == UNKNOWN else row["total"]) * row["dims"]
        row.update(id=i, sequence_hash=123)
        row.update({mode: [0x3f000000] * count for mode in MODES})
        if row["dims"] == 2 and row["total"] == 16 and row["depth"] == 0 and not row["pseudo"]:
            row["naive_resume"][0] = 0x3e800000
        records.append(row)
    return [{"schema": 1, "simd_width": 8, "cases": len(records)}, *records]


class NativeSamplerReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def save(self, data, name="samples.jsonl"):
        path = self.root / name
        path.write_text("\n".join(json.dumps(row) for row in data), encoding="utf-8")
        return path

    def test_complete_repeated_corpus_with_negative_control(self):
        path = self.save(corpus())
        result = compare([path, path])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["cases"], 648)
        self.assertGreater(result["different_components"]["naive_resume"], 0)

    def test_real_restoration_mismatch_fails(self):
        data = corpus()
        data[1]["chunked"][0] = 0x3e800000
        result = compare([self.save(data)] * 2)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["different_components"]["chunked"], 1)

    def test_cross_execution_drift_fails(self):
        first = self.save(corpus())
        other = corpus()
        other[1]["reordered"][0] = 0x3e800000
        second = self.save(other, "second.jsonl")
        result = compare([first, second])
        self.assertFalse(result["all_execution_records_identical"])
        self.assertEqual(result["status"], "failed")

    def test_missing_negative_control_fails(self):
        data = corpus()
        for row in data[1:]:
            row["naive_resume"] = row["baseline"][:]
        self.assertEqual(compare([self.save(data)] * 2)["status"], "failed")

    def test_missing_duplicate_or_truncated_cases_rejected(self):
        for mode in ("missing", "duplicate", "values"):
            data = corpus()
            if mode == "missing":
                data.pop()
            elif mode == "duplicate":
                data[2] = data[1].copy()
            else:
                data[1]["baseline"].pop()
            with self.assertRaises(ValueError):
                read(self.save(data))

    def test_nonfinite_out_of_range_and_nonwords_rejected(self):
        for word in (0x7fc00000, 0x7f800000, 0x3f800000, 0xbf000000, -1, 2**32, True):
            data = corpus()
            data[1]["baseline"][0] = word
            with self.assertRaises(ValueError):
                read(self.save(data))

    def test_wrong_simd_contract_rejected(self):
        data = corpus()
        data[0]["simd_width"] = 16
        with self.assertRaises(ValueError):
            read(self.save(data))

    def test_compressed_reference_and_drift(self):
        actual = self.save(corpus())
        reference = self.root / "reference.jsonl.gz"
        reference.write_bytes(gzip.compress(actual.read_bytes(), mtime=0))
        self.assertTrue(matches_reference(actual, reference))
        data = corpus()
        data[1]["sequence_hash"] = 124
        self.assertFalse(matches_reference(self.save(data), reference))

    def test_committed_native_reference_validates(self):
        reference = Path(__file__).resolve().parents[1] / "xpu2/reference/sampler-avx8-20261016.jsonl.gz"
        result = compare([reference, reference])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["components_per_mode"], 47304)
        self.assertEqual(result["different_components"]["naive_resume"], 2916)

    def handoff(self):
        baseline = corpus()
        chunks = sum(((65 if r["total"] == UNKNOWN else r["total"]) + 6) // 7
                     for r in baseline[1:])
        retries = sum((r["id"] + start) % 5 == 0 for r in baseline[1:]
                      for start in range(0, 65 if r["total"] == UNKNOWN else r["total"], 7))
        header = {"schema": 2, "simd_width": 8, "cases": 648, "guards": 11,
                  "waits": chunks, "retries": retries, "transfers": 0, "work": [chunks]}
        return [header, *({"id": r["id"], "values": r["baseline"]} for r in baseline[1:])]

    def test_handoff_matches_reference_and_checks_coverage(self):
        reference = self.save(corpus(), "reference.jsonl")
        handoff = self.save(self.handoff())
        self.assertEqual(compare_handoffs([handoff, handoff], reference)["status"], "passed")

    def test_handoff_sample_drift_fails(self):
        reference = self.save(corpus(), "reference.jsonl")
        data = self.handoff()
        data[1]["values"][0] = 0x3e800000
        result = compare_handoffs([self.save(data)] * 2, reference)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["different_components"]["transport_vs_pinned"], 2)

    def test_handoff_missing_wait_retry_or_guard_rejected(self):
        reference = self.save(corpus(), "reference.jsonl")
        for name in ("waits", "retries", "guards"):
            data = self.handoff()
            data[0][name] -= 1
            with self.assertRaises(ValueError):
                compare_handoffs([self.save(data)] * 2, reference)

    def test_handoff_must_actually_use_multiple_workers(self):
        reference = self.save(corpus(), "reference.jsonl")
        data = self.handoff()
        total = sum(data[0]["work"])
        for work, transfers in (([total, 0], 1), ([total // 2] * 2, 0), ([total], 1)):
            data[0].update(work=work, transfers=transfers)
            with self.assertRaises(ValueError):
                compare_handoffs([self.save(data)] * 2, reference)
        data[0].update(work=[total // 2] * 2, transfers=1)
        self.assertEqual(compare_handoffs([self.save(data)] * 2, reference)["status"], "passed")

    def test_handoff_duplicate_or_partial_results_rejected(self):
        reference = self.save(corpus(), "reference.jsonl")
        for kind in ("duplicate", "partial", "nonword"):
            data = self.handoff()
            if kind == "duplicate":
                data[2] = data[1]
            elif kind == "partial":
                data[1]["values"].pop()
            else:
                data[1]["values"][0] = True
            with self.assertRaises(ValueError):
                compare_handoffs([self.save(data)] * 2, reference)

    def test_extended_native_cmj_reference(self):
        reference = Path(__file__).resolve().parents[1] / "xpu2/reference/sampler-cmj-avx8-20261017.jsonl.gz"
        result = compare([reference, reference])
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["cases"], 234)
        self.assertEqual(result["components_per_mode"], 18792)

    def test_single_execution_cannot_certify_repeat(self):
        with self.assertRaises(ValueError):
            compare([self.save(corpus())])


if __name__ == "__main__":
    unittest.main()
