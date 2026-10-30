import struct
import unittest
from pathlib import Path
from xpu2.cuda_samples import records, validate, checksum

REFERENCE = Path(__file__).resolve().parents[1] / "xpu2/reference/sampler-avx8-20261016.jsonl.gz"


class CudaSamplerChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = records(REFERENCE)
        cls.returned = b"".join(row["output"] for row in cls.records)
        cls.words = [value for row in cls.records for value in row["result"]]

    def test_reference_coverage_is_explicit(self):
        result = validate(self.records, self.returned, self.words)
        self.assertTrue(result["passed"])
        self.assertEqual(result["supported_records"], 17226)
        self.assertEqual(result["unsupported_records"], 6434)
        self.assertEqual(result["invalid_records"], 11)
        self.assertEqual(result["compared_sample_components"], 34452)

    def test_unsupported_state_and_output_are_preserved(self):
        for row in self.records:
            if row["result"][0] == 1:
                self.assertEqual(row["input"], row["output"])
                self.assertEqual(row["result"][2:], [0, 0, 0])

    def test_supported_cursor_advances_exactly_once(self):
        for row in self.records:
            if row["result"][0] == 0:
                before = struct.unpack("<15I", row["input"])
                after = struct.unpack("<15I", row["output"])
                self.assertEqual(after[5], before[5] + 1)
                self.assertEqual(after[:5] + after[6:14], before[:5] + before[6:14])
                self.assertEqual(after[14], checksum(row["output"][:56]))

    def test_changed_result_is_not_hidden_by_other_matches(self):
        words = self.words[:]
        supported = next(i for i, r in enumerate(self.records) if r["result"][0] == 0)
        words[supported*5+2] ^= 1
        result = validate(self.records, self.returned, words)
        self.assertFalse(result["passed"])
        self.assertEqual(result["sample_or_status_mismatch_records"], 1)

    def test_changed_state_is_detected_independently_of_samples(self):
        data = bytearray(self.returned)
        data[20] ^= 1
        result = validate(self.records, bytes(data), self.words)
        self.assertFalse(result["passed"])
        self.assertEqual(result["state_mismatch_records"], 1)

    def test_truncated_results_rejected(self):
        for data, words in ((self.returned[:-1], self.words), (self.returned, self.words[:-1])):
            with self.assertRaises(ValueError):
                validate(self.records, data, words)

    def test_native_tables_enable_full_original_corpus_only(self):
        data = records(REFERENCE, tables=True)
        result = validate(data, b"".join(r["output"] for r in data),
                          [v for r in data for v in r["result"]])
        self.assertTrue(result["passed"])
        self.assertEqual(result["supported_records"], 23652)
        self.assertEqual(result["compared_sample_components"], 47304)
        self.assertEqual(result["unsupported_records"], 8)

    def test_late_indices_and_unvalidated_counts_stay_declined(self):
        for data in (records(REFERENCE, tables=True), records(REFERENCE)):
            guards = [r for r in data if r["case"] == "unsupported"]
            self.assertEqual(len(guards), 8)
            self.assertTrue(all(r["result"][0] == 1 and r["input"] == r["output"] for r in guards))

    def test_extended_cmj_corpus(self):
        reference = REFERENCE.with_name("sampler-cmj-avx8-20261017.jsonl.gz")
        data = records(reference)
        result = validate(data, b"".join(r["output"] for r in data),
                          [v for r in data for v in r["result"]])
        self.assertEqual(result["compared_sample_components"], 18792)
        self.assertEqual(result["supported_records"], 9396)
        self.assertEqual(result["unsupported_records"], 8)

    def test_unknown_distribution_cannot_silently_approximate(self):
        words = self.words[:]
        index = next(i for i, r in enumerate(self.records) if r["result"][0] == 1)
        words[index*5] = 0
        self.assertFalse(validate(self.records, self.returned, words)["passed"])


if __name__ == "__main__":
    unittest.main()
