"""Deferred export regressions; run explicitly, never by installation."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import rdla,coordinates
from test_compatibility_035 import scene

class Compatibility039(unittest.TestCase):
 def test_all_dispatch_patterns_use_supported_attributes(self):
  for order in range(9):
   value=scene();value['render_settings']={'batch_tile_order':order}
   text=rdla.scene_text(value)
   self.assertIn('["progressive_tile_order"] = %d,'%order,text)
   self.assertIn('["checkpoint_tile_order"] = %d,'%order,text)
   self.assertNotIn('["batch_tile_order"]',text)
 def test_projection_reference_uv_is_nondegenerate(self):
  uv=coordinates.fallback_uvs([[0,1,2],[0,2,3,4]])
  self.assertEqual(len(uv),7)
  a,b,c=uv[:3]
  self.assertNotEqual((b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]),0)

if __name__=='__main__':unittest.main()
