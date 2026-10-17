import copy
import struct
import unittest
from xpu2.live_env import VARIANTS,coverage

def words(values):return list(struct.unpack('<%dI'%len(values),struct.pack('<%df'%len(values),*values)))
class EnvCoverage(unittest.TestCase):
    def cases(self):
        rows=[]
        for name in VARIANTS:
            hit=name not in ('hemisphere_down','short_ray');lit=hit and name!='black'
            sample=words([0,0,1,.2,.1,.05,.25,0])
            result=[100,1 if lit else 0,0,0,1,0,0,0]
            light=[int(hit),100 if hit else 0,.1 if hit else 0,1 if lit else 0,0,0,0,0]
            rows.append(dict(variant=name,sample=sample,expected=words(result+light)))
        return rows
    def test_complete(self):self.assertEqual(coverage(self.cases())['sphere']['hits'],1)
    def test_missing_variant(self):
        with self.assertRaises(ValueError):coverage(self.cases()[:-1])
    def test_unknown_variant(self):
        rows=self.cases();rows[0]['variant']='textured'
        with self.assertRaises(ValueError):coverage(rows)
    def test_truncated(self):
        rows=self.cases();rows[0]['expected'].pop()
        with self.assertRaises(ValueError):coverage(rows)
    def test_invalid_native_output(self):
        for index,value in ((0,float('nan')),(7,1)):
            rows=self.cases();rows[0]['sample'][index]=words([value])[0]
            with self.assertRaises(ValueError):coverage(rows)
    def test_black_or_missed_light_cannot_contribute(self):
        for row in (2,5):
            rows=self.cases();rows[row]['expected'][1]=words([1])[0]
            with self.assertRaises(ValueError):coverage(rows)
    def test_indirect_and_lit_coverage_required(self):
        for index in (1,4):
            rows=self.cases();rows[0]['expected'][index]=0
            with self.assertRaises(ValueError):coverage(rows)
    def test_hemisphere_hit_coverage(self):
        rows=self.cases();rows[4]=copy.deepcopy(rows[3]);rows[4]['variant']='hemisphere_down'
        with self.assertRaises(ValueError):coverage(rows)
