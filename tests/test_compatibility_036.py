"""Deferred checks for 0.3.6; intentionally not run during implementation."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import buckets,options,rdla,motion,geometry,native_light_links,asset_library,package_store
from test_compatibility_035 import scene

class Compatibility036(unittest.TestCase):
 def test_bucket_packet_bounds(self):
  self.assertEqual(buckets.parse('@@MODO_TILES 2 17 19 0,0,8,8 16,16,17,19'),(2,17,19,[(0,0,8,8),(16,16,17,19)]))
  for line in ('@@MODO_TILES -1 16 16','@@MODO_TILES 0 16 16 0,0,17,8','@@MODO_TILES 0 0 16','@@MODO_TILES 0 16 16 x','noise'):
   self.assertIsNone(buckets.parse(line))
 def test_tile_order_all_render_modes(self):
  value=scene();value['render_settings']={'batch_tile_order':7}
  text=rdla.scene_text(value)
  for key in ('batch_tile_order','progressive_tile_order','checkpoint_tile_order'):self.assertIn('["%s"] = 7'%key,text)
  with self.assertRaises(ValueError):options.render_values({'batch_tile_order':9})
 def test_shared_translation_and_override_expansion(self):
  value=scene();mesh=value['meshes'][0];mesh['instances']=[list(rdla.IDENTITY)];mesh['instance_ids']=['owner|0']
  a=copy.deepcopy(value);b=copy.deepcopy(value);b['meshes'][0]['instances'][0][12]=2
  result=motion.apply_motion(value,a,b,[-.25,.25])
  # apply_motion publishes on the supplied scene, matching capture_frame.
  result=value if result is None else result
  mesh=result['meshes'][0]
  self.assertEqual(mesh['instance_velocities'],[[96.,0.,0.]])
  expanded=list(geometry.render_meshes([mesh],expand_instances={'owner'}))[0]
  self.assertEqual(expanded['matrix_close'][12],2)
  self.assertNotIn('instances',expanded)
 def test_explicit_light_item_rule_overrides_shader_rule(self):
  links={'materials':{'mat':{'mode':'include','members':['a']}},'lights':{'b':{'mode':'include','members':['mesh']}}}
  self.assertEqual(native_light_links.allowed(links,'mesh|3','mat',{'a','b','c'}),['a','b'])
 def test_material_presets_have_valid_native_parameters(self):
  files=list((asset_library.bundled()/'materials').glob('*.moonmat.json'))
  self.assertEqual(len(files),8)
  for path in files:asset_library.read_preset(path)
 def test_asset_collection_content_and_tampering(self):
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);source=root/'source.tx';source.write_bytes(b'asset bytes');store=root/'shared';a=root/'a.tx';b=root/'b.tx'
   package_store.copy(source,a,store);package_store.copy(source,b,store)
   self.assertEqual(a.read_bytes(),source.read_bytes());self.assertEqual(b.read_bytes(),source.read_bytes())
   canonical=next(store.iterdir());canonical.write_bytes(b'modified')
   with self.assertRaises(ValueError):package_store.copy(source,root/'c.tx',store)

if __name__=='__main__':unittest.main()
