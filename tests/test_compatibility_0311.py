"""Deferred checks. Do not run automatically.
Host checks after installation: OCIO/LUT+AOV switching during render and after
completion; camera/material/single-mesh edits; structural edits; cancellation;
RDL polygon UV/part/instance/camera import and Undo; duplicate/missing motion IDs.
Set MOONRAY_TEST_RUNTIME to a staged runtime for native pipe checks.
"""
import json,os,struct,subprocess,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import geometry_ids,rdl_import,native

class Compatibility0311(unittest.TestCase):
 def test_point_reordering_and_missing_ids(self):
  center={'kind':'points','ids':['a','b'],'vertices':[[0,0,0],[1,0,0]]}
  sample={'kind':'points','ids':['b','a'],'vertices':[[2,0,0],[0,1,0]],'radii':[.2,.1]}
  aligned=geometry_ids.align(center,sample)
  self.assertEqual(aligned['vertices'],[[0,1,0],[2,0,0]])
  self.assertEqual(aligned['radii'],[.1,.2])
  with self.assertRaises(ValueError):geometry_ids.align({'kind':'points','vertices':[]},{'kind':'points','vertices':[]})
 def test_rdl_layer_and_world_positions(self):
  matrix=list(rdl_import.IDENTITY);matrix[12]=3
  records=[{'name':'vars','type':'SceneVariables','attributes':{'layer':'layer'}},
   {'name':'layer','type':'Layer','attributes':{'geometries':['mesh'],'parts':[''],'surface_shaders':['material']}},
   {'name':'mesh','type':'RdlMeshGeometry','attributes':{'vertex_list_0':[[0,0,0],[1,0,0],[0,1,0]],'face_vertex_count':[3],'vertices_by_index':[0,1,2],'node_xform':matrix,'uv_list':[[0,0],[1,0],[0,1]],'is_subd':False}},
   {'name':'material','type':'DwaBaseMaterial','attributes':{'albedo':[.3,.4,.5]}}]
  data=rdl_import.plan({'version':1,'objects':records},'test.rdla')
  # The mesh keeps its own points; where it stands is the item's transform.
  self.assertEqual(data['meshes'][0]['vertices'][0],[0,0,0])
  self.assertEqual(data['meshes'][0]['matrix'][12],3)
  self.assertTrue(data['meshes'][0]['render'])
  self.assertEqual(data['instances'],[])
  self.assertEqual(data['meshes'][0]['tags'],['material'])
  self.assertEqual(data['materials']['material']['graph']['nodes']['material']['parameters']['albedo'],[.3,.4,.5])
  records[2]['attributes']['vertices_by_index']=[0,1,99]
  # A mesh that does not hold together is left out and named, and the rest of the scene still comes in.
  broken=rdl_import.plan({'version':1,'objects':records},'test.rdla')
  self.assertEqual(broken['meshes'],[])
  self.assertTrue(any('mesh is not imported' in w for w in broken['warnings']))
  self.assertIn('material',broken['materials'])
 @unittest.skipUnless(os.environ.get('MOONRAY_TEST_RUNTIME'),'Native check explicitly requires a runtime')
 def test_reused_display_pipe_orientation_and_black(self):
  runtime=Path(os.environ['MOONRAY_TEST_RUNTIME'])
  args=[str(runtime/'modo_display_stream.exe'),'beauty','raw','0','rec709','','display','','','','','1 0 0 0 1 0 0 0 1']
  frame=struct.pack('<III',2,2,0)+struct.pack('<12f',1,0,0,0,1,0,0,0,1,0,0,0)
  result=subprocess.run(args,input=frame+frame,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=native.environment(runtime),timeout=30,check=True)
  self.assertEqual(len(result.stdout),56)
  for offset in (0,28):
   self.assertEqual(struct.unpack('<III',result.stdout[offset:offset+12]),(1,2,2))
   self.assertEqual(result.stdout[offset+12:offset+28],bytes([0,0,255,255,0,0,0,255,255,0,0,255,0,255,0,255]))

if __name__=='__main__':unittest.main()
