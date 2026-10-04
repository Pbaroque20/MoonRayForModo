"""Deferred compatibility regressions; never run by the installer."""
import copy,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import materialx,materialx_definitions,materialx_document,motion,rdla,environment_layers,native_light_links
from test_compatibility_035 import scene

class Compatibility038(unittest.TestCase):
 def test_inherited_defaults_and_version_selection(self):
  document=ET.fromstring('<materialx><nodedef name="base" node="constant" version="1"><input name="value" type="color3" value="1,0,0"/><output name="out" type="color3"/></nodedef><nodedef name="new" node="constant" inherit="base" version="2" isdefaultversion="true"><input name="value" value="0,1,0"/></nodedef></materialx>')
  materialx_definitions.normalize(document);defs={d.get('name'):d for d in document}
  chosen=materialx_definitions.select(ET.fromstring('<constant type="color3"/>'),defs)
  self.assertEqual(chosen.get('name'),'new');self.assertEqual(chosen.find('input').get('type'),'color3')
  self.assertEqual(chosen.find('input').get('value'),'0,1,0')
  with self.assertRaises(ValueError):materialx_definitions.select(ET.fromstring('<constant type="color3" version="3"/>'),defs)
 def test_inheritance_cycles_are_rejected(self):
  with self.assertRaises(ValueError):materialx_definitions.normalize(ET.fromstring('<materialx><nodedef name="a" inherit="b"/><nodedef name="b" inherit="a"/></materialx>'))
 def test_standard_surface_extra_controls(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'material.mtlx'
   path.write_text('<materialx version="1.38"><standard_surface name="s" type="surfaceshader"><input name="opacity" type="color3" value="0.25,0.25,0.25"/><input name="specular_rotation" type="float" value="0.25"/><input name="transmission_extra_roughness" type="float" value="0.3"/></standard_surface><surfacematerial name="m"><input name="surfaceshader" type="surfaceshader" nodename="s"/></surfacematerial></materialx>',encoding='utf-8')
   graph=materialx.read(path);item=graph['nodes'][graph['root']]
   self.assertEqual(item['parameters']['presence'],.25)
   self.assertAlmostEqual(item['parameters']['shading_tangent'][1],1)
   self.assertIn('independent_transmission_roughness',item['inputs'])
 def test_standard_surface_subsurface_builds_layer(self):
  with tempfile.TemporaryDirectory() as folder:
   path=Path(folder)/'sss.mtlx'
   path.write_text('<materialx><standard_surface name="s" type="surfaceshader"><input name="subsurface" type="float" value="0.5"/><input name="subsurface_radius" type="color3" value="1,0.2,0.1"/></standard_surface><surfacematerial name="m"><input name="surfaceshader" type="surfaceshader" nodename="s"/></surfacematerial></materialx>',encoding='utf-8')
   graph=materialx.read(path);root=graph['nodes'][graph['root']]
   self.assertEqual(root['type'],'DwaLayerMaterial');self.assertEqual(root['parameters']['mask'],.5)
   foreground=graph['nodes'][root['inputs']['material_A']]
   self.assertIn('scattering_radius',foreground['inputs']);self.assertIn('scattering_color',foreground['inputs'])
 def test_rotating_instances_keep_one_prototype(self):
  value=scene();mesh=value['meshes'][0];mesh['instances']=[list(rdla.IDENTITY)]*2;mesh['instance_ids']=['owner|a','owner|b']
  first=copy.deepcopy(value);last=copy.deepcopy(value)
  last['meshes'][0]['instances'][0]=[0,1,0,0,-1,0,0,0,0,0,1,0,0,0,0,1]
  motion.apply_motion(value,first,last,[-.25,.25])
  self.assertEqual(len(value['meshes']),1);self.assertTrue(value['meshes'][0]['instance_transform_motion'])
  text=rdla.scene_text(value)
  self.assertEqual(text.count('local geometry = RdlMeshGeometry'),1)
  self.assertEqual(text.count('local movingInstance = RdlInstancerGeometry'),2)
  self.assertIn('["node_xform"] = blur(',text)
 def test_environment_alpha_metadata_and_blend(self):
  self.assertEqual(environment_layers.alpha_index('prefix <ImageSpec><alpha_channel>3</alpha_channel></ImageSpec>'),3)
  self.assertEqual(environment_layers.alpha_index('<ImageSpec><alpha_channel>-1</alpha_channel></ImageSpec>'),-1)
  self.assertEqual(environment_layers.blend([0,0,1],[1,0,0],'normal',.25),[.25,0,.75])
  with self.assertRaises(ValueError):environment_layers.alpha_index('invalid')
 def test_native_links_do_not_readd_excluded_environment(self):
  value=scene();value['native_light_links']={'materials':{'':{'mode':'exclude','members':['sky']}}}
  lines=[];native_light_links.emit(value,value['meshes'],{'sky':['sky_ref'],'key':['key_ref'],'__environment__':['sky_ref']},['sky_ref'],lines)
  definitions=[line for line in lines if line.startswith('LightSet(')]
  self.assertTrue(definitions);self.assertNotIn('sky_ref',''.join(definitions));self.assertIn('key_ref',''.join(definitions))

if __name__=='__main__':unittest.main()
