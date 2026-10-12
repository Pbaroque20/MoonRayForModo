"""Authored RDL normal data is preserved in import plans; malformed data is reported."""
import unittest
from test_rdl_sets import scene
from moonray_modo import rdl_import
class Normals(unittest.TestCase):
 def plan(self,normals):
  source=scene({});source['objects'][2]['attributes']['normal_list']=normals
  return rdl_import.plan(source,'test.rdla')
 def test_valid_normals_retained(self):
  values=[[0,0,1]]*3;data=self.plan(values)
  self.assertTrue(any(m['normals']==values for m in data['meshes']))
 def test_invalid_normals_reported(self):
  for values in ([[0,0,1]],[[0,0,0]]*3,[[0,float('nan'),1]]*3,[[1,0]]*3):
   with self.subTest(values=values):
    data=self.plan(values)
    self.assertTrue(any('invalid authored normals' in w for w in data['warnings']))
    self.assertTrue(all(not m['normals'] for m in data['meshes']))
if __name__=='__main__':unittest.main()
