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
