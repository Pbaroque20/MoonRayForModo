from pathlib import Path
import struct
import unittest
from xpu2.cuda_samples import checksum, validate
from xpu2.cuda_window_samples import packet, records, continuation_cases

REFERENCE=Path(__file__).resolve().parents[1]/'xpu2/reference/sampler-window-avx8-20261017.jsonl.gz'

class CUDAWindowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows=records(REFERENCE)

    def output(self, rows):
        return b''.join(r['output'] for r in rows), [v for r in rows for v in r['result']]

    def test_native_expectations_and_negative_control(self):
        states, words=self.output(self.rows)
        result=validate(self.rows, states, words, stride=64)
        self.assertTrue(result['passed'])
        self.assertEqual(result['supported_records'],27108)
        self.assertEqual(result['compared_sample_components'],54216)
        self.assertEqual(result['unsupported_records'],5)
        self.assertEqual(result['invalid_records'],12)
        native=[r for r in self.rows if r.get('mode')=='baseline']
        naive=[r for r in self.rows if r.get('mode')=='index_only']
        self.assertEqual(sum(a!=b for x,y in zip(native,naive) for a,b in zip(x['result'][2:],y['result'][2:])),2268)

    def test_envelopes_are_versioned_and_checksummed(self):
        for row in self.rows:
            if row['result'][0]==2:
                continue
            words=struct.unpack('<16I',row['output'])
            self.assertEqual(words[1],2)
            self.assertEqual(words[15],checksum(row['output'][:60]))
            self.assertLessEqual(words[14],words[5])
            self.assertLessEqual(words[5]-words[14],8)

    def test_returned_state_continuity(self):
        cases=continuation_cases(self.rows)
        self.assertEqual(len(cases),324)
        self.assertEqual(sum(map(len,cases.values())),13554)
        self.assertEqual(max(map(len,cases.values())),48)
        for samples in cases.values():
            for previous,current in zip(samples,samples[1:]):
                self.assertEqual(previous['output'],current['input'])

    def test_missing_case_prefix_or_tail_rejected(self):
        first=next(r for r in self.rows if r.get('mode')=='baseline')
        for sample in (first['sample'],1047):
            partial=[r for r in self.rows if not (r['case']==first['case'] and r.get('mode')=='baseline' and r['sample']==sample)]
            with self.assertRaises(ValueError):
                continuation_cases(partial)
        with self.assertRaises(ValueError):
            continuation_cases([r for r in self.rows if r['case']!=first['case']])

    def test_discontinuous_return_state_rejected(self):
        changed=[dict(r) for r in self.rows]
        first=next(r for r in changed if r.get('mode')=='baseline')
        first['output']=first['input']
        with self.assertRaises(ValueError):
            continuation_cases(changed)

    def test_missing_tables_decline_and_preserve_every_valid_state(self):
        rows=records(REFERENCE,tables=False)
        self.assertTrue(all(r['input']==r['output'] for r in rows))
        result=validate(rows,*self.output(rows),stride=64)
        self.assertTrue(result['passed'])
        self.assertEqual(result['supported_records'],0)
        self.assertEqual(result['unsupported_records'],27113)
        self.assertEqual(result['invalid_records'],12)

    def test_state_sample_and_status_corruption_fail(self):
        rows=self.rows[:1]
        states,words=self.output(rows)
        wrong=bytearray(states);wrong[56]^=1
        self.assertEqual(validate(rows,bytes(wrong),words,stride=64)['state_mismatch_records'],1)
        for slot in (0,1,2):
            bad=words[:];bad[slot]^=1
            self.assertEqual(validate(rows,states,bad,stride=64)['sample_or_status_mismatch_records'],1)

    def test_truncated_or_wrong_stride_rejected(self):
        rows=self.rows[:1];states,words=self.output(rows)
        for data,result,stride in ((states[:-1],words,64),(states,words[:-1],64),(states,words,60)):
            with self.assertRaises(ValueError):
                validate(rows,data,result,stride=stride)

if __name__=='__main__':
    unittest.main()
