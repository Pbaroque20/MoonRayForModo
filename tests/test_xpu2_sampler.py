import gzip
import itertools
import json
from pathlib import Path
import tempfile
import unittest

from xpu2.sampler import UNKNOWN, FIELDS, MODES, read, compare, matches_reference


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

    def test_single_execution_cannot_certify_repeat(self):
        with self.assertRaises(ValueError):
            compare([self.save(corpus())])


if __name__ == "__main__":
    unittest.main()
