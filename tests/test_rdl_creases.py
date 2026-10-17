import unittest
from test_rdl_sets import scene
from moonray_modo import rdl_import
class Creases(unittest.TestCase):
 def test_sharpness_becomes_modo_weight(self):
  # Sharpness 10 or more is a weight of 1; below, a tenth of it.
  a={'subd_crease_indices':[0,1,1,2],'subd_crease_sharpnesses':[10,2],'subd_corner_indices':[0],'subd_corner_sharpnesses':[20]}
  self.assertEqual(rdl_import.hard_creases(a,[[0,1,2]],3),([[0,1,1.0],[1,2,0.2]],[[0,1.0]],True))
 def test_invalid_topology_or_weights(self):
  for a in ({'subd_crease_indices':[0,1]}, {'subd_crease_indices':[0,0],'subd_crease_sharpnesses':[10]}, {'subd_corner_indices':[3],'subd_corner_sharpnesses':[10]}, {'subd_corner_indices':[0],'subd_corner_sharpnesses':[float('nan')]}):
   with self.subTest(a=a),self.assertRaises(ValueError):rdl_import.hard_creases(a,[[0,1,2]],3)
 def test_plan_carries_creases(self):
  data=scene({});data['objects'][2]['attributes'].update(is_subd=True,subd_crease_indices=[0,1],subd_crease_sharpnesses=[10])
  plan=rdl_import.plan(data,'test.rdla')
  self.assertTrue(any(m['hard_edges']==[[0,1,1.0]] for m in plan['meshes']))
 def test_semi_sharp_is_imported_without_a_warning(self):
  data=scene({});data['objects'][2]['attributes'].update(is_subd=True,subd_crease_indices=[0,1],subd_crease_sharpnesses=[3])
  plan=rdl_import.plan(data,'test.rdla')
  self.assertTrue(any(m['hard_edges']==[[0,1,0.3]] for m in plan['meshes']))
  self.assertFalse(any('semi-sharp' in w for w in plan['warnings']))
if __name__=='__main__':unittest.main()
