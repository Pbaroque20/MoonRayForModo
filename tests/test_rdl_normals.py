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
    # Left out, the mesh shades as MoonRay shades one given none: the triangle's own facing.
    self.assertTrue(all(m['normals']==[[0,0,1]]*3 for m in data['meshes']))
class MoonRaysOwn(unittest.TestCase):
 CUBE=[[x,y,z] for x in (0,1) for y in (0,1) for z in (0,1)]
 QUADS=[[0,1,3,2],[4,6,7,5],[0,4,5,1],[2,3,7,6],[0,2,6,4],[1,5,7,3]]
 def test_given_none_a_cube_is_smooth_as_moonray_shades_it(self):
  normals=rdl_import.shaded_normals(self.CUBE,self.QUADS)
  self.assertEqual(len(normals),8)
  # Each corner of a cube points out along its diagonal, as the three faces around it add up.
  for point,normal in zip(self.CUBE,normals):
   expected=[(c-.5)/abs(c-.5)/3**.5 for c in point]
   for got,want in zip(normal,expected):self.assertAlmostEqual(got,want)
 def test_without_smooth_normal_each_face_keeps_its_own(self):
  normals=rdl_import.shaded_normals(self.CUBE,self.QUADS,smooth=False)
  self.assertEqual(len(normals),24)
  self.assertEqual(normals[:4],[[-1.0,0.0,0.0]]*4)
 def test_bigger_faces_count_for_more(self):
  points=[[0,0,0],[1,0,0],[0,1,0],[0,0,1],[0,0,-9]]
  faces=[[0,1,2],[0,3,1],[0,1,4]]
  normal=rdl_import.shaded_normals(points,faces)[0]
  self.assertGreater(abs(normal[1]),abs(normal[2]))
 def test_a_plan_brings_them_in_unless_subdivided(self):
  source=scene({})
  data=rdl_import.plan(source,'test.rdla')
  self.assertTrue(all(m['normals']==[[0,0,1]]*3 for m in data['meshes']))
  source=scene({});source['objects'][2]['attributes']['is_subd']=True;source['objects'][3]['attributes']['is_subd']=True
  data=rdl_import.plan(source,'test.rdla')
  self.assertTrue(all(m['normals']==[] for m in data['meshes']))
class NormalTransforms(unittest.TestCase):
 def test_shear_stays_perpendicular_to_transformed_tangents(self):
  matrix=[2,1,0,0,0,3,0,0,0,0,4,0,8,9,10,1]
  normal=rdl_import.transformed_normals([[0,1,0]],matrix)[0]
  self.assertAlmostEqual(sum(a*b for a,b in zip(normal,[2,1,0])),0)
  self.assertAlmostEqual(sum(v*v for v in normal),1)
  self.assertLess(normal[0],0);self.assertGreater(normal[1],0)
 def test_translation_ignored_and_nonuniform_scale_inverted(self):
  matrix=[2,0,0,0,0,1,0,0,0,0,1,0,100,200,300,1]
  normal=rdl_import.transformed_normals([[1,1,0]],matrix)[0]
  self.assertAlmostEqual(normal[1]/normal[0],2)
 def test_tiny_uniform_scale_is_not_singular(self):
  matrix=[1e-20,0,0,0,0,1e-20,0,0,0,0,1e-20,0,0,0,0,1]
  self.assertEqual(rdl_import.transformed_normals([[0,0,1]],matrix),[[0,0,1]])
 def test_singular_rejected(self):
  for scale in (0,):
   matrix=rdl_import.IDENTITY[:];matrix[0]=scale
   with self.assertRaises(ValueError):rdl_import.transformed_normals([[0,0,1]],matrix)
class Reflections(unittest.TestCase):
 def test_reflection_normal_sign(self):
  matrix=rdl_import.IDENTITY[:];matrix[0]=-1
  self.assertEqual(rdl_import.transformed_normals([[1,0,0],[0,0,1]],matrix),[[-1,0,0],[0,0,1]])
  self.assertLess(rdl_import.normal_transform(matrix)[1],0)
if __name__=='__main__':unittest.main()
