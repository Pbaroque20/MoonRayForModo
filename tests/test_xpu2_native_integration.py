import json
import struct
import unittest
from xpu2.native_integration import summary,records,verify_counts

class NativeIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.counts=dict(batches=1,samples=1,accepted=1,replaced=1,unsupported=0,invalid=0,mismatch=0,errors=0)
        self.src=struct.pack('<24I',0x32535058,1,*([0]*22))
        self.native=[0,0,0x3f800000,0x3e800000,0x3e800000,0x3e800000,0x3e800000,0]
    def frame(self,result=None):
        return b'XNI1'+self.src+struct.pack('<8I',*self.native)+struct.pack('<9I',*(result if result is not None else [0,*self.native]))
    def test_exact_replacement_and_audit_counts(self):
        observed=records(self.frame())
        verify_counts(self.counts,observed,'replace')
        verify_counts(dict(self.counts,replaced=0),observed,'audit')
        with self.assertRaises(ValueError):verify_counts(self.counts,observed,'audit')
    def test_corrupt_truncated_and_unknown_records(self):
        for data in (b'',self.frame()[:-1],self.frame()+b'x',b'bad!'+self.frame()[4:],self.frame([3]+[0]*8)):
            with self.assertRaises(ValueError):records(data)
    def test_nonzero_declined_outputs_rejected(self):
        with self.assertRaises(ValueError):records(self.frame([1,1]+[0]*7))
    def test_mismatch_is_not_hidden_by_native_fallback(self):
        result=[0,*self.native];result[4]+=1
        observed=records(self.frame(result))
        self.assertEqual(observed['mismatch'],1)
        self.assertEqual(observed['rgb_mismatches'],1)
        counts=dict(self.counts,accepted=0,replaced=0,mismatch=1)
        with self.assertRaises(ValueError):verify_counts(counts,observed,'replace')
    def test_unsupported_control_requires_actual_decline(self):
        observed=records(self.frame([1]+[0]*8))
        counts=dict(self.counts,accepted=0,replaced=0,unsupported=1)
        verify_counts(counts,observed,'unsupported')
        with self.assertRaises(ValueError):verify_counts(counts,observed,'replace')
    def test_nonfinite_outputs_cannot_pass(self):
        self.native[3]=0x7fc00000
        observed=records(self.frame())
        self.assertEqual(observed['nonfinite'],1)
        with self.assertRaises(ValueError):verify_counts(self.counts,observed,'replace')
    def test_final_summary_required_and_count_integrity(self):
        log=json.dumps(dict(self.counts,samples=0))+'\n'+json.dumps(self.counts)
        self.assertEqual(summary(log),self.counts)
        for row in ({},dict(self.counts,errors=-1),dict(self.counts,replaced=2),dict(self.counts,samples=True)):
            with self.assertRaises(ValueError):summary(json.dumps(row))
        with self.assertRaises(ValueError):summary('CUDA_ERROR driver unavailable')
        with self.assertRaises(ValueError):verify_counts(dict(self.counts,samples=2),records(self.frame()),'replace')

if __name__=='__main__':unittest.main()
