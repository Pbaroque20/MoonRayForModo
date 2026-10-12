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
  self.assertTrue(any('first 2 of its 3' in w for w in data['warnings']))

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
