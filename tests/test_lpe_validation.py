import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import lpe_validation
class NativeLpe(unittest.TestCase):
 def test_missing_output_is_not_success(self):
  with tempfile.TemporaryDirectory() as path:
   with self.assertRaisesRegex(ValueError,'did not produce'):lpe_validation.results(path,1,0,'')
 def test_failed_process_is_not_success(self):
  with tempfile.TemporaryDirectory() as path:
   with self.assertRaisesRegex(ValueError,'failed'):lpe_validation.results(path,1,1,'failure')
 def test_native_rejection_identifies_output(self):
  with tempfile.TemporaryDirectory() as path:
   result=lpe_validation.results(path,1,0,'Error: skipping active render output /check/output/0: invalid light path expression')
   self.assertEqual(set(result),{0})
 def test_bounds(self):
  with tempfile.TemporaryDirectory() as path:
   for expressions in ([],['x']*129,['x'*4097]):
    with self.assertRaises(ValueError):lpe_validation.prepare(path,expressions)
