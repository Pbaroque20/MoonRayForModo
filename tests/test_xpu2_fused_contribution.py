import struct
import unittest
from xpu2.fused_contribution import join

def word(f):return struct.unpack('<I',struct.pack('<f',f))[0]
def packed(magic,words):return magic+struct.pack('<%dI'%len(words),*words)

class FusedBoundary(unittest.TestCase):
    def fixture(self):
        m=[0]*28;m[0]=(77<<16)|96;m[8]=1;m[26]=9;m[24:26]=[word(.25),word(.5)];m[19:22]=[word(1.)]*3
        src=[0]*24;src[:2]=[0x32535058,1];src[4]=src[7]=src[10]=word(1.);src[11:13]=m[24:26];src[14:20]=[word(1.)]*6
        sample=[word(x) for x in (0,0,1,.2,.1,.05,.25,0)]
        ids=[m[k] for k in (0,1,2,3,10,11,13,12)]
        inp=[0.]*24;inp[:8]=[9,4,1,0,0,10,.1,.25];inp[8:11]=[1,1,1];inp[11:14]=[.2,.1,.05];inp[14:17]=[1,1,1]
        return m+src+sample,ids+[word(x) for x in inp]+[0]*8
    def test_valid_join(self):
        a,b=self.fixture();rows,missing=join(packed(b'XCL1',a),packed(b'XCR1',b));self.assertEqual(len(rows),1);self.assertEqual(missing,[])
    def test_unmatched_is_explicit(self):
        a,b=self.fixture();other=b.copy();other[5]=1
        rows,missing=join(packed(b'XCL1',a),packed(b'XCR1',b+other));self.assertEqual(len(rows),1);self.assertEqual(len(missing),1)
    def test_malformed(self):
        a,b=self.fixture()
        for raw in (b'',b'XCR1',packed(b'BAD!',b),packed(b'XCR1',b)[:-1]):
            with self.assertRaises(ValueError):join(packed(b'XCL1',a),raw)
    def test_ambiguous_identity(self):
        a,b=self.fixture()
        with self.assertRaises(ValueError):join(packed(b'XCL1',a+a),packed(b'XCR1',b))
    def test_duplicate_contribution(self):
        a,b=self.fixture()
        with self.assertRaises(ValueError):join(packed(b'XCL1',a),packed(b'XCR1',b+b))
    def test_no_match(self):
        a,b=self.fixture();b[5]=1
        with self.assertRaises(ValueError):join(packed(b'XCL1',a),packed(b'XCR1',b))
    def test_boundary_values_must_match(self):
        for index in (15,16,19):
            a,b=self.fixture();b[index]=word(.7)
            with self.assertRaises(ValueError):join(packed(b'XCL1',a),packed(b'XCR1',b))
    def test_unsupported_domain(self):
        for index,value in ((8,0),(9,-1),(10,.5),(11,1),(12,1),(13,0),(15,0),(25,1),(14,float('nan'))):
            a,b=self.fixture();b[index]=word(value)
            with self.assertRaises(ValueError):join(packed(b'XCL1',a),packed(b'XCR1',b))
    def test_invalid_sample(self):
        a,b=self.fixture();a[-1]=word(1.)
        with self.assertRaises(ValueError):join(packed(b'XCL1',a),packed(b'XCR1',b))
