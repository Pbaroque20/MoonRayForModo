import struct
import unittest
from xpu2.correlated_state import decode,match_surface

def word(v):return struct.unpack('<I',struct.pack('<f',v))[0]
class CorrelatedTests(unittest.TestCase):
    def fixture(self,changes=None):
        m=[0]*28;m[0]=(77<<16)|96;m[4]=1;m[8]=1;m[9]=0xffffffff;m[26]=1
        m[24:26]=[word(.25),word(.75)]
        src=[0]*24;src[:2]=[0x32535058,1];src[11:13]=m[24:26]
        out=[0]*8
        words=m+src+out
        for index,value in (changes or {}).items():words[index]=value
        return b'XCL1'+struct.pack('<60I',*words)
    def test_same_call_randoms_and_counter(self):
        r=decode(self.fixture())[0]
        self.assertEqual(r['metadata'][24:26],r['input'][11:13])
        self.assertEqual(r['metadata'][8],r['metadata'][7]+1)
    def test_rejects_corrupt_context_and_packet(self):
        for i,v in ((8,2),(13,8),(14,2),(27,1),(26,0),(28,0),(39,word(.5)),(24,word(float('nan')))):
            with self.subTest(i=i),self.assertRaises(ValueError):decode(self.fixture({i:v}))
    def test_rejects_invalid_framing(self):
        good=self.fixture()
        for raw in (b'XCL1',good[:-1],good+b'x',b'BAD!'+good[4:],b'XCL1'+good[4:]*1025):
            with self.assertRaises(ValueError):decode(raw)
    def test_surface_requires_unique_identity_and_orientation(self):
        r=decode(self.fixture());s={'ids':{'pixel':(77<<16)|96,'subpixel':0,'sequence':0,'nonmirror_depth':0},
          'fields':{'position':[0.,0.,0.],'throughput':[0.,0.,0.],'normal':[0.,0.,0.],
                    'geometric_normal':[0.,0.,0.],'direction':[0.,0.,0.]}}
        self.assertEqual(len(match_surface(r,[s])),1)
        for cases in ([],[s,s]):
            with self.assertRaises(ValueError):match_surface(r,cases)
        s['fields']['geometric_normal'][0]=1.
        with self.assertRaises(ValueError):match_surface(r,[s])

    def test_retains_material_normal_separately(self):
        r=decode(self.fixture())
        s={'ids':{'pixel':(77<<16)|96,'subpixel':0,'sequence':0,'nonmirror_depth':0},
           'fields':{'position':[0.,0.,0.],'throughput':[0.,0.,0.],'normal':[0.,0.,1.],
                     'geometric_normal':[0.,0.,0.],'direction':[0.,0.,0.]}}
        result=match_surface(r,[s])[0]
        self.assertFalse(result['normal_stages_equal'])
        self.assertEqual(result['surface_normal'],[0.,0.,1.])
        self.assertEqual(result['lambert_normal'],[0.,0.,0.])
        self.assertEqual(r[0]['input'][2:5],[0,0,0])

if __name__=='__main__':unittest.main()
