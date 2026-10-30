import struct
import unittest
from xpu2.surface_state import decode, RECORD

class SurfaceStateTests(unittest.TestCase):
    def fixture(self, ids=None, floats=None):
        u=[0]*24;u[0]=(77<<16)|96;u[23]=1
        f=[0.0]*64;f[3]=1.0
        for i,v in (ids or {}).items():u[i]=v
        for i,v in (floats or {}).items():f[i]=v
        return b'XNS1'+RECORD.pack(*u,*f)
    def test_preserves_explicit_identity_and_float32_bits(self):
        row=decode(self.fixture(ids={2:0xffffffff,3:9,9:321,12:31},floats={21:-0.0,38:0.25}))[0]
        self.assertEqual(row['ids']['sequence'],0xffffffff)
        self.assertEqual(row['ids']['dependencies'],31)
        self.assertEqual(row['fields']['throughput'],[0.25,0.0,0.0])
        self.assertEqual(struct.pack('<f',row['fields']['position'][0]),struct.pack('<I',0x80000000))
    def test_rejects_bad_framing_and_counts(self):
        good=self.fixture()
        for raw in (b'',b'XNS1',b'BAD!'+good[4:],good[:-1],good+b'x',b'XNS1'+good[4:]*1025):
            with self.subTest(size=len(raw)),self.assertRaises(ValueError):decode(raw)
    def test_rejects_nonfinite_or_reserved_values(self):
        for index,value in ((0,float('nan')),(7,float('inf')),(54,1.0),(63,-1.0)):
            with self.subTest(index=index),self.assertRaises(ValueError):decode(self.fixture(floats={index:value}))
    def test_rejects_unknown_flags_and_sample_identity(self):
        for index,value in ((6,2),(7,2),(12,32),(0,42),(1,1)):
            with self.subTest(index=index),self.assertRaises(ValueError):decode(self.fixture(ids={index:value}))
    def test_derivative_validity_controls_storage(self):
        for index in (9,20,32,37):
            with self.subTest(index=index),self.assertRaises(ValueError):decode(self.fixture(floats={index:1.0}))
        rows=decode(self.fixture(ids={6:1,7:1},floats={9:1.0,32:2.0}))
        self.assertEqual(rows[0]['fields']['origin_x'][0],1.0)
        self.assertEqual(rows[0]['fields']['dpds'][0],2.0)
    def test_keeps_repeated_path_events_separate(self):
        a=self.fixture();b=self.fixture(ids={4:1,2:123})
        rows=decode(a+b[4:])
        self.assertEqual(len(rows),2)
        self.assertEqual([row['ids']['ray_depth'] for row in rows],[0,1])

if __name__=='__main__':unittest.main()
