import unittest
from test_rdl_sets import scene
from moonray_modo import rdl_import
class Creases(unittest.TestCase):
 def test_hard_subset_and_warning(self):
  a={'subd_crease_indices':[0,1,1,2],'subd_crease_sharpnesses':[10,2],'subd_corner_indices':[0],'subd_corner_sharpnesses':[20]}
  self.assertEqual(rdl_import.hard_creases(a,[[0,1,2]],3),([[0,1]],[0],True))
 def test_invalid_topology_or_weights(self):
  for a in ({'subd_crease_indices':[0,1]}, {'subd_crease_indices':[0,0],'subd_crease_sharpnesses':[10]}, {'subd_corner_indices':[3],'subd_corner_sharpnesses':[10]}, {'subd_corner_indices':[0],'subd_corner_sharpnesses':[float('nan')]}):
   with self.subTest(a=a),self.assertRaises(ValueError):rdl_import.hard_creases(a,[[0,1,2]],3)
 def test_plan_carries_creases(self):
  data=scene({});data['objects'][2]['attributes'].update(is_subd=True,subd_crease_indices=[0,1],subd_crease_sharpnesses=[10])
  plan=rdl_import.plan(data,'test.rdla')
  self.assertTrue(any(m['hard_edges']==[[0,1]] for m in plan['meshes']))
if __name__=='__main__':unittest.main()
