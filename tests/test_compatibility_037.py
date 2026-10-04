"""Deferred 0.3.7 checks. Not executed during implementation."""
import copy, json, math, shutil, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import coordinates, geometry_ids, material_bundle, nodes, rdla, shared_image

class Compatibility037(unittest.TestCase):
 def test_affine_matches_corner_transform(self):
  layer={'uv_matrix':[1,.2,.3,-.1,1,.7],'rotation':.75,'scale':[-2,3]}
  matrix,offset=coordinates.affine(layer)
  points=[[0,0],[1,0],[.2,.9],[-1,2]]
  for (u,v),expected in zip(points,coordinates.transform_uv(layer,points)):
   actual=[matrix[0]*u+matrix[1]*v+offset[0],matrix[2]*u+matrix[3]*v+offset[1]]
   for a,b in zip(actual,expected):self.assertAlmostEqual(a,b)
  with self.assertRaises(ValueError):coordinates.affine({'scale':[0,1]})
  self.assertEqual(rdla.vector([1,2,3,4],'Vec4'),'Vec4(1, 2, 3, 4)')
 def test_point_identity_reordering_and_births(self):
  a={'kind':'points','ids':['a','b'],'vertices':[[0,0,0],[1,0,0]]}
  b={'kind':'points','ids':['b','a'],'vertices':[[2,0,0],[0,1,0]],'radii':[.2,.1]}
  result=geometry_ids.align(a,b)
  self.assertEqual(result['vertices'],[[0,1,0],[2,0,0]])
  self.assertEqual(result['radii'],[.1,.2]);self.assertEqual(b['ids'],['b','a'])
  b['ids']=['a','c']
  with self.assertRaises(ValueError):geometry_ids.align(a,b)
 def test_strand_identity_reorders_vertices(self):
  a={'kind':'curves','ids':[1,2],'counts':[2,3],'vertices':[[0,0,0]]*5}
  b={'kind':'curves','ids':[2,1],'counts':[3,2],'vertices':[[i,0,0] for i in range(5)]}
  result=geometry_ids.align(a,b)
  self.assertEqual(result['counts'],[2,3]);self.assertEqual([v[0] for v in result['vertices']],[3,4,0,1,2])
 def test_protocol_rejects_wrong_owner_before_opening_mapping(self):
  for packet in ('bad','@@MODO_SHARED 1 beauty 1 1 Local\\MoonRayForModo_2_1'):
   with self.assertRaises(ValueError):shared_image.receive(packet,1)
 def test_bundle_relocation_and_tamper(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);texture=root/'original.png';texture.write_bytes(b'fixture asset, copied without decoding')
   graph=nodes.new();graph['nodes']['texture']={'type':'image','parameters':{'file':str(texture)},'inputs':{},'position':[0,0]}
   entry={'name':'Portable','settings':{'node_graph':graph,'node_override':True}}
   manifest=material_bundle.save('source',lambda identity:entry,root/'bundle')
   shutil.move(str(manifest.parent),str(root/'relocated'));texture.unlink()
   manifest=root/'relocated/material.moonmat.json';data=material_bundle.load(manifest)
   moved=Path(data['materials']['material0']['settings']['node_graph']['nodes']['texture']['parameters']['file'])
   self.assertTrue(moved.is_file());moved.write_bytes(b'tampered')
   with self.assertRaises(ValueError):material_bundle.load(manifest)

if __name__=='__main__':unittest.main()
