import copy
import json
from pathlib import Path
import struct
import tempfile
import unittest
from xpu2.lambert import read,compare,records,validate

REFERENCE=Path(__file__).resolve().parents[1]/'xpu2/reference/lambert-eval-20261017.jsonl.gz'

class LambertTests(unittest.TestCase):
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

    def test_native_coverage_repeat_and_compression(self):
        r=compare([REFERENCE,self.save(self.data)])
        self.assertEqual(r['status'],'passed');self.assertEqual(r['cases'],11520)
        self.assertEqual(r['components_per_mode'],80640)
        with self.assertRaises(ValueError):compare([REFERENCE])

    def test_physical_oracle_invariants(self):
        validity=set();pdf_positive=pdf_zero=0
        for r in self.data[1:]:
            v=struct.unpack('<7f',struct.pack('<7I',*r['output'][:7]))
            validity.add(r['output'][7]);pdf_positive+=v[3]>0;pdf_zero+=v[3]==0
            # Black albedo or zero scale must extinguish RGB and albedo, not PDF.
            if r['key'][4]==0 or r['key'][5]==0:
                self.assertEqual(v[:3]+v[4:],(0.,)*6)
            if r['key']==[0,0,0,0,1,1,1,1]:
                self.assertEqual(r['output'][:4],[0x3ea2f983]*4)
                self.assertEqual(v[4:],(1.,1.,1.))
                self.assertEqual(r['output'][7],0)
        self.assertEqual(validity,{0,1});self.assertGreater(pdf_zero,0);self.assertGreater(pdf_positive,0)

    def test_incomplete_duplicate_and_relabelled_cases_rejected(self):
        for mode in ('missing','duplicate','key','controls'):
            data=copy.deepcopy(self.data)
            if mode=='missing':data.pop()
            elif mode=='duplicate':data[2]=data[1]
            elif mode=='key':data[1]['key'][0]=True
            else:data[1]['input'][22]=1
            with self.subTest(mode=mode),self.assertRaises(ValueError):read(self.save(data))

    def test_invalid_normal_color_result_and_geometry_rejected(self):
        for field,index,value in [('input',2,0x7fc00000),('input',4,0),('input',14,0xbf800000),('output',0,0x7f800000),('output',7,2)]:
            data=copy.deepcopy(self.data);data[1][field][index]=value
            with self.subTest(field=field,index=index),self.assertRaises(ValueError):read(self.save(data))

    def test_repeated_native_drift_fails(self):
        data=copy.deepcopy(self.data);data[1]['output'][0]=1
        self.assertEqual(compare([REFERENCE,self.save(data)])['status'],'failed')

    def test_gpu_expected_values_and_guards(self):
        states=b''.join(r['output'] for r in self.records)
        words=[v for r in self.records for v in r['result']]
        result=validate(self.records,states,words)
        self.assertTrue(result['passed']);self.assertEqual(result['supported_records'],11520)
        self.assertEqual(result['unsupported_records'],4);self.assertEqual(result['invalid_records'],11)
        self.assertEqual(result['geometric_validity_checks'],11520)
        self.assertTrue(all(r['input']==r['output'] for r in self.records))

    def test_shader_result_geometry_and_status_drift_fail(self):
        rows=self.records[:1];states=rows[0]['output'];words=rows[0]['result']
        for slot in (0,1,4,5,8):
            corrupt=words[:];corrupt[slot]^=1
            self.assertFalse(validate(rows,states,corrupt)['passed'])
        state=bytearray(states);state[4]^=1
        self.assertFalse(validate(rows,bytes(state),words)['passed'])

    def test_truncated_gpu_data_rejected(self):
        rows=self.records[:1];state=rows[0]['output'];words=rows[0]['result']
        for data,result,stride in ((state[:-1],words,96),(state,words[:-1],96),(state,words,64)):
            with self.assertRaises(ValueError):validate(rows,data,result,stride=stride)

if __name__=='__main__':unittest.main()
