import unittest
from test_rdl_sets import scene
from moonray_modo import rdl_import

def translated(x):
 m=rdl_import.IDENTITY[:];m[12]=x;return m

class NestedTransforms(unittest.TestCase):
 def fixture(self,outer_use=None):
  source=scene({})
  source['objects'][2]['attributes']['node_xform']=translated(.1)
  inner={'method':2,'references':['/geo/wall'],'xform_list':[translated(.2)],'node_xform':translated(.3),'use_reference_xforms':True}
  outer={'method':2,'references':['inner'],'xform_list':[translated(.4)],'node_xform':translated(.5)}
  if outer_use is not None:outer['use_reference_xforms']=outer_use
  source['objects'] += [{'name':'inner','type':'RdlInstancerGeometry','attributes':inner},{'name':'outer','type':'RdlInstancerGeometry','attributes':outer}]
  return source
 def test_nested_transform_applied_once(self):
  for use,want in [(True,1.5),(False,1.2),(None,1.2)]:
   with self.subTest(use=use):
    data=rdl_import.plan(self.fixture(use),'test.rdla')
    mesh=next(m for m in data['meshes'] if m['name']=='wall')
    self.assertAlmostEqual(mesh['matrix'][12],want)
 def test_reference_transform_default_is_disabled_at_each_level(self):
  source=self.fixture();del source['objects'][-2]['attributes']['use_reference_xforms']
  data=rdl_import.plan(source,'test.rdla')
  mesh=next(m for m in data['meshes'] if m['name']=='wall')
  self.assertAlmostEqual(mesh['matrix'][12],1.1)

class InstanceTransformValidation(unittest.TestCase):
 def test_large_quaternion_keeps_rotation(self):
  expected=rdl_import.placed([1,2,3],[0,0,1,1],[2,3,4])
  actual=rdl_import.placed([1,2,3],[0,0,1e200,1e200],[2,3,4])
  for a,b in zip(actual,expected):self.assertAlmostEqual(a,b)
 def test_invalid_components_raise_value_error(self):
  for position,orientation,scale in [([1,2],None,None),([1,2,float('nan')],None,None),
      ([0,0,0],[0,0,float('inf'),1],None),([0,0,0],[0,1],None),
      ([0,0,0],None,[1,2]),([0,0,0],None,[1,1,float('inf')])]:
   with self.subTest(position=position,orientation=orientation,scale=scale):
    with self.assertRaises(ValueError):rdl_import.placed(position,orientation,scale)
 def test_zero_scale_and_zero_quaternion_remain_valid(self):
  value=rdl_import.placed([1,2,3],[0,0,0,0],[0,2,3])
  self.assertEqual(len(value),16)
  self.assertEqual(value[:3],[0,0,0])
  self.assertEqual(value[12:],[1,2,3,1])

 def test_invalid_instancer_is_reported_without_losing_other_geometry(self):
  source=scene({})
  source['objects'].append({'name':'bad','type':'RdlInstancerGeometry','attributes':{
   'method':0,'references':['/geo/wall'],'positions':[[0,0,float('nan')]]}})
  data=rdl_import.plan(source,'test.rdla')
  self.assertTrue(any(m['name']=='floor' for m in data['meshes']))
  self.assertFalse(any(m['name']=='wall' for m in data['meshes']))
  self.assertTrue(any('Invalid instance position' in w for w in data['warnings']))
