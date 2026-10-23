import unittest
from reference_repeatability import envelope,against
from run_speed_comparison import metric,quality
class ReferenceControls(unittest.TestCase):
 def test_rare_original_is_not_hidden_by_zero_training(self):
  controls=[[.1,0.,0.,1.],[.10001,0.,0.,1.]];bound=envelope(controls)
  self.assertGreater(bound,0);self.assertTrue(against(controls[1],controls,bound)['passed'])
  self.assertFalse(against([.10002,0.,0.,1.],controls,bound)['passed'])
 def test_no_nearest_image_only_shortcut(self):
  self.assertFalse(against([.10001],[[.1],[.10001]],0)['passed'])
class QualityGates(unittest.TestCase):
 def test_relative_mse_and_alpha(self):
  reference=[1.,2.,2.,1.]*64;actual=[2.,2.,2.,0.]*64
  m=metric(actual,reference,8,8);self.assertAlmostEqual(m['relative_mse'],1/9)
  self.assertEqual(m['alpha'],1);self.assertFalse(quality(m))
 def test_block_bias_cannot_hide_in_sample_noise(self):
  reference=[.5,.5,.5,1.]*64;actual=[.52,.52,.52,1.]*64
  m=metric(actual,reference,8,8);self.assertAlmostEqual(m['max_block_mean'],.02)
  self.assertFalse(quality(m));self.assertTrue(quality(metric(reference,reference,8,8)))
if __name__=='__main__':unittest.main()
