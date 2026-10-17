import unittest
from unittest.mock import patch
from test_rdl_sets import scene
from moonray_modo import rdl_import

class InstanceAttributeLimit(unittest.TestCase):
 def test_import_limit_keeps_original_per_instance_value_indices(self):
  source=scene({})
  source['objects'] += [
   {'name':'colors','type':'UserData','attributes':{'color_key':'Cd','color_values_0':[[1,0,0],[0,1,0],[0,0,1]]}},
   {'name':'instances','type':'RdlInstancerGeometry','attributes':{'method':2,'references':['/geo/wall'],
    'xform_list':[rdl_import.IDENTITY]*3,'primitive_attributes':['colors']}}]
  with patch.object(rdl_import,'INSTANCE_LIMIT',2):data=rdl_import.plan(source,'test.rdla')
  mesh=next(m for m in data['meshes'] if m['name']=='wall')
  instance=next(i for i in data['instances'] if i['source']=='wall')
  self.assertEqual(mesh['attributes'],[{'name':'Cd','type':'color','value':[1,0,0]}])
  self.assertEqual(instance['attributes'],[{'name':'Cd','type':'color','value':[0,1,0]}])
  self.assertTrue(any('of its 3 instances, the first 2' in w for w in data['warnings']))
  # The third copy, past the limit, comes in merged into a mesh, with its own colour.
  merged=next(m for m in data['meshes'] if m['name']=='instances merged 1')
  self.assertEqual(merged['attributes'],[{'name':'Cd','type':'color','value':[0,0,1]}])
  self.assertTrue(merged['render'])

 def test_disabled_indices_do_not_shift_values_after_limit(self):
  source=scene({})
  source['objects'] += [
   {'name':'ids','type':'UserData','attributes':{'int_key':'id','int_values_0':[10,20,30,40]}},
   {'name':'instances','type':'RdlInstancerGeometry','attributes':{'method':2,'references':['/geo/wall'],
    'xform_list':[rdl_import.IDENTITY]*4,'disable_indices':[0],'primitive_attributes':['ids']}}]
  with patch.object(rdl_import,'INSTANCE_LIMIT',3):data=rdl_import.plan(source,'test.rdla')
  mesh=next(m for m in data['meshes'] if m['name']=='wall')
  instance=next(i for i in data['instances'] if i['source']=='wall')
  self.assertEqual(mesh['attributes'][0]['value'],20)
  self.assertEqual(instance['attributes'][0]['value'],30)
  merged=next(m for m in data['meshes'] if m['name']=='instances merged 1')
  self.assertEqual(merged['attributes'][0]['value'],40)


class MergedPastLimit(unittest.TestCase):
 def plan(self, count, limit, points=None, moving=False):
  source=scene({})
  moved=lambda x:[1,0,0,0, 0,2,0,0, 0,0,1,0, x,0,0,1]
  source['objects'][2]['attributes']['normal_list']=[[0,0,1]]*3
  source['objects'] += [
   {'name':'ids','type':'UserData','attributes':{'int_key':'id','int_values_0':list(range(count))}},
   {'name':'tags','type':'UserData','attributes':{'string_key':'kind','string_values':['tree']*count}},
   {'name':'instances','type':'RdlInstancerGeometry','attributes':{'method':2,'references':['/geo/wall'],
    'xform_list':[moved(i) for i in range(count)],'primitive_attributes':['ids','tags']}}]
  with patch.object(rdl_import,'INSTANCE_LIMIT',limit):
   if points:
    with patch.object(rdl_import,'MERGED_POINTS',points):return rdl_import.plan(source,'test.rdla')
   return rdl_import.plan(source,'test.rdla')

 def test_copies_past_the_limit_are_merged_in_place(self):
  data=self.plan(5,2)
  self.assertEqual(len([i for i in data['instances'] if i['source']=='wall']),1)
  merged=next(m for m in data['meshes'] if m['name']=='instances merged 1')
  self.assertEqual(len(merged['vertices']),9)
  self.assertEqual(merged['vertices'][3:6],[[3,0,0],[4,0,0],[3,2,0]])
  self.assertEqual(merged['faces'],[[0,1,2],[3,4,5],[6,7,8]])
  self.assertEqual(merged['matrix'],rdl_import.IDENTITY)
  self.assertEqual(merged['normals'][0],[0,0,1])
  # A value each copy has its own of is a value face by face; one they share stays the mesh's own.
  self.assertEqual(merged['maps'],[('id','float','faces',[[2.0],[3.0],[4.0]])])
  self.assertEqual(merged['attributes'],[{'name':'kind','type':'string','value':'tree'}])

 def test_merged_meshes_are_split_by_points(self):
  data=self.plan(6,1,points=6)
  merged=sorted(m['name'] for m in data['meshes'] if 'merged' in m['name'])
  self.assertEqual(merged,['instances merged 1','instances merged 2','instances merged 3'])

 def test_a_turned_normal_stays_square_to_a_stretched_surface(self):
  stretched=[2,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]
  normal=rdl_import.turned([1,1,0],stretched)
  self.assertAlmostEqual(normal[0]*2+normal[1]*-1, 0.0)
