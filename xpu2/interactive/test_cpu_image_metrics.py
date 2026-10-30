import json,unittest
from pathlib import Path
from run_cpu_image import compare_fixture
class ImageMetrics(unittest.TestCase):
 def setUp(self):
  self.gates=json.loads((Path(__file__).parent/'surface-gates.json').read_text())
  self.values=[.5,.3,.2,1]*3072
  self.reference={'channels':{n:[v]*3072 for n,v in zip('RGBA',(.5,.3,.2,1))}}
 def test_identical(self):
  self.assertEqual(compare_fixture(self.values,self.reference,self.gates)['R']['max_pixel'],0)
 def test_nonfinite(self):
  for v in (float('nan'),float('inf'),float('-inf')):
   self.values[0]=v
   with self.assertRaises(ValueError):compare_fixture(self.values,self.reference,self.gates)
 def test_nonfinite_reference(self):
  self.reference['channels']['B'][1]=float('nan')
  with self.assertRaises(ValueError):compare_fixture(self.values,self.reference,self.gates)
 def test_truncated(self):
  with self.assertRaises(ValueError):compare_fixture(self.values[:-1],self.reference,self.gates)
 def test_spatial_error(self):
  self.values[0]+=.061
  with self.assertRaises(ValueError):compare_fixture(self.values,self.reference,self.gates)
 def test_block_bias(self):
  for i in range(3072):self.values[i*4]+=.011
  with self.assertRaises(ValueError):compare_fixture(self.values,self.reference,self.gates)
 def test_alpha(self):
  self.values[3]=.999
  with self.assertRaises(ValueError):compare_fixture(self.values,self.reference,self.gates)
if __name__=='__main__':unittest.main()
