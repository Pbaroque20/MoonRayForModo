import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from xpu2.lambert_sample import read,compare,records,validate,metrics,floats

REFERENCE=Path(__file__).resolve().parents[1]/'xpu2/reference/lambert-sample-avx8-20261017.jsonl.gz'

class LambertSamplingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data=read(REFERENCE)
        cls.records=records(REFERENCE)

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'corpus.jsonl'

    def save(self,data):
        self.path.write_text('\n'.join(json.dumps(r) for r in data),encoding='utf-8')
        return self.path

    def test_repeatability_is_separate_from_vector_parity(self):
        report=compare([REFERENCE,self.save(self.data)])
        self.assertEqual(report['status'],'passed')
        self.assertEqual(report['cases'],7680)
        self.assertEqual(report['components_per_mode'],53760)
        self.assertFalse(report['cpp_vector_bitwise_parity'])
        self.assertEqual(report['geometric_validity_differences'],96)
        self.assertLess(report['cpp_vs_vector']['direction']['max_absolute'],2e-7)
        with self.assertRaises(ValueError):compare([REFERENCE])

    def test_grazing_classification_differences_are_not_hidden_by_rgb_error(self):
        bad=[r for r in self.data[1:] if r['cpp'][7]!=r['vector'][7]]
        self.assertEqual(len(bad),96)
        self.assertEqual({r['key'][7] for r in bad},{3,4})
        self.assertEqual(sum(r['key'][7]==3 for r in bad),48)
        self.assertLess(max(abs(a-b) for r in bad for a,b in zip(floats(r['cpp'][3:6]),floats(r['vector'][3:6]))),1e-6)

    def test_sampling_physical_invariants(self):
        pdfs=set()
        for r in self.data[1:]:
            for mode in ('cpp','vector'):
                v=floats(r[mode][:7]);pdfs.add(v[6]>0)
                if r['key'][4]==0:self.assertEqual(v[3:6],(0.,0.,0.))
                if r['key'][7]==1: # r1=1 yields the normal at the hemisphere pole.
                    self.assertEqual(v[:3],floats(r['input'][2:5]))
        self.assertEqual(pdfs,{False,True})

    def test_incomplete_duplicate_relabelled_and_invalid_records_rejected(self):
        for action in ('missing','duplicate','boolean_key','controls','reserved'):
            data=copy.deepcopy(self.data)
            if action=='missing':data.pop()
            elif action=='duplicate':data[2]=data[1]
            elif action=='boolean_key':data[1]['key'][0]=False
            elif action=='reserved':data[1]['input'][13]=1
            else:data[1]['input'][22]=1
            with self.subTest(action=action),self.assertRaises(ValueError):read(self.save(data))

    def test_bad_math_inputs_and_outputs_rejected(self):
        for field,index,value in [('input',2,0x7fc00000),('input',4,0),('input',11,0x40000000),
                                  ('input',12,0xbf800000),('input',14,0xbf800000),
                                  ('cpp',0,0x7f800000),('vector',7,2),('cpp',3,0xbf800000)]:
            data=copy.deepcopy(self.data);data[1][field][index]=value
            with self.subTest(field=field,index=index),self.assertRaises(ValueError):read(self.save(data))

    def test_either_native_execution_drift_fails(self):
        for mode in ('cpp','vector'):
            data=copy.deepcopy(self.data);data[1][mode][3]=1
            self.assertEqual(compare([REFERENCE,self.save(data)])['status'],'failed')

    def test_expected_gpu_values_and_declines(self):
        states=b''.join(r['output'] for r in self.records)
        words=[v for r in self.records for v in r['result']]
        report=validate(self.records,states,words)
        self.assertTrue(report['passed']);self.assertFalse(report['vector_bitwise_parity'])
        self.assertEqual(report['supported_records'],7680)
        self.assertEqual(report['unsupported_records'],4)
        self.assertEqual(report['invalid_records'],13)
        self.assertEqual(report['comparisons']['vector']['geometric_validity_differences'],96)

    def test_numeric_bit_status_and_validity_drift_fail(self):
        rows=self.records[:1];state=rows[0]['output'];words=rows[0]['result']
        for slot in (0,1,4,7,8):
            corrupt=words[:];corrupt[slot]^=1
            self.assertFalse(validate(rows,state,corrupt)['passed'])
        corrupted=bytearray(state);corrupted[4]^=1
        self.assertFalse(validate(rows,bytes(corrupted),words)['passed'])
        corrupt=words[:];corrupt[4]=0x7fc00000
        r=validate(rows,state,corrupt)
        self.assertFalse(r['passed']);self.assertFalse(r['finite_outputs'])
        self.assertIsNone(r['comparisons']['cpp']['rgb']['max_absolute'])

    def test_guard_payload_corruption_rejected(self):
        rows=self.records[-1:];words=rows[0]['result'][:];words[1]=1
        r=validate(rows,rows[0]['output'],words)
        self.assertFalse(r['passed']);self.assertEqual(r['guard_mismatch_records'],1)

    def test_shuffle_keeps_canonical_result_hash(self):
        def check(rows):
            return validate(rows,b''.join(r['output'] for r in rows),[v for r in rows for v in r['result']])
        original=check(self.records[:5]);reversed_result=check(self.records[:5][::-1])
        self.assertEqual(original['canonical_result_sha256'],reversed_result['canonical_result_sha256'])
        changed=copy.deepcopy(self.records[:5]);changed[0]['result'][1]^=1
        self.assertNotEqual(original['canonical_result_sha256'],check(changed)['canonical_result_sha256'])

    def test_truncated_gpu_data_rejected(self):
        rows=self.records[:1];state=rows[0]['output'];words=rows[0]['result']
        for data,result,stride in ((state[:-1],words,96),(state,words[:-1],96),(state,words,64)):
            with self.assertRaises(ValueError):validate(rows,data,result,stride=stride)

    def test_signed_zero_is_bitwise_but_not_numeric_difference(self):
        r=metrics([(0,0x80000000)])
        self.assertEqual(r['different_bits'],1);self.assertEqual(r['numerically_different'],0)
        self.assertEqual(r['max_absolute'],0)

if __name__=='__main__':unittest.main()
