import copy
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from xpu2.window_samples import anchors, compare, read

REFERENCE = Path(__file__).resolve().parents[1] / 'xpu2/reference/sampler-window-avx8-20261017.jsonl.gz'


class SamplerWindowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        with gzip.open(REFERENCE, 'rt', encoding='utf-8') as stream:
            self.data = [json.loads(line) for line in stream]

    def save(self, data=None, name='test.jsonl'):
        path = self.root / name
        path.write_text('\n'.join(json.dumps(r) for r in (self.data if data is None else data)), encoding='utf-8')
        return path

    def test_pinned_native_boundary_evidence(self):
        result = compare([REFERENCE, REFERENCE])
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['cases'], 324)
        self.assertEqual(result['components_per_mode'], 27108)
        self.assertEqual(result['different_components'], {'restored': 0, 'index_only': 2268})

    def test_window_anchor_before_refill(self):
        # Snapshot is taken BEFORE the next draw: the boundary still names the
        # preceding full window. A restore consumes it before the native refill.
        self.assertEqual(anchors(1009, 1015)[:5], [1009, 1009, 1009, 1017, 1017])
        self.assertEqual(anchors(0, 1000)[:3], [992, 1000, 1000])

    def test_single_execution_rejected(self):
        with self.assertRaises(ValueError):
            compare([REFERENCE])

    def test_missing_or_invalid_guard_coverage(self):
        for key, value in [('schema', 1), ('simd_width', 16), ('guards', 5), ('cases', 323)]:
            data = copy.deepcopy(self.data)
            data[0][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                read(self.save(data))

    def test_missing_or_duplicate_case(self):
        for kind in ['missing', 'duplicate', 'wrong_origin', 'bool_dimension']:
            data = copy.deepcopy(self.data)
            if kind == 'missing':
                data.pop()
            elif kind == 'duplicate':
                data[2] = copy.deepcopy(data[1])
                data[2]['id'] = 1
            elif kind == 'wrong_origin':
                data[1]['origin'] = 8
            else:
                data[1]['dims'] = True
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                read(self.save(data))

    def test_truncated_or_nonfloat_samples(self):
        for bad in [None, -1, 2**32, True, 0x7fc00000, 0x7f800000, 0x3f800000, 0xbf000000]:
            data = copy.deepcopy(self.data)
            if bad is None:
                data[1]['baseline'].pop()
            else:
                data[1]['baseline'][0] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                read(self.save(data))

    def test_invalid_anchor_interval_or_hash(self):
        for field, value in [('anchors', [1000] * 48), ('begin', 1001), ('sequence_hash', True)]:
            data = copy.deepcopy(self.data)
            data[1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                read(self.save(data))

    def test_restored_mismatch_fails(self):
        self.data[1]['restored'][0] ^= 1
        path = self.save()
        result = compare([path, path])
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['different_components']['restored'], 1)

    def test_missing_negative_control_fails(self):
        for row in self.data[1:]:
            row['index_only'] = row['baseline'][:]
        path = self.save()
        self.assertEqual(compare([path, path])['status'], 'failed')

    def test_cross_execution_drift_fails(self):
        self.data[1]['sequence_hash'] ^= 1
        result = compare([REFERENCE, self.save()])
        self.assertFalse(result['all_execution_records_identical'])
        self.assertEqual(result['status'], 'failed')

    def test_plain_and_compressed_records_equal(self):
        self.assertEqual(read(REFERENCE), read(self.save()))


if __name__ == '__main__':
    unittest.main()
