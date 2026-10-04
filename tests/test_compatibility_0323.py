"""Deferred checks for limits, link groups and affine graph bases; not run on install."""
import sys,types,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import shader_library,native_light_links,graph_coordinates,nodes

class Compatibility0323(unittest.TestCase):
    def test_metal_color_rejected_but_hdr_map_allowed(self):
        spec=shader_library.catalog()['DwaMetalMaterial']['attributes']['metallic_color']
        for v in ([-.1,0,1],[8,0,0]):
            with self.assertRaises(ValueError):shader_library.typed(v,spec)
        self.assertEqual(shader_library.typed([1,0,.2],spec),[1,0,.2])
        self.assertEqual(shader_library.typed([8,8,8],nodes.specs('constant')['value']),[8,8,8])
    def test_vector_bounds_and_nonfinite_values(self):
        for value in ([0,2],[0,float('nan')]):
            with self.assertRaises(ValueError):shader_library.typed(value,{'type':'Vec2f','min':0,'max':1})
    def test_group_none_empty_and_union(self):
        def group(name,items):return types.SimpleNamespace(type='group',id=name,items=items)
        def owner(groups):return types.SimpleNamespace(itemGraph=lambda _:types.SimpleNamespace(forward=lambda:groups))
        fake=types.SimpleNamespace(Group=lambda v:v)
        with patch.dict(sys.modules,{'modo':fake}):
            self.assertIsNone(native_light_links.linked_members(owner([])))
            self.assertEqual(native_light_links.linked_members(owner([group('empty',[])])),[])
            light=types.SimpleNamespace(type='pointLight',id='light')
            self.assertEqual(native_light_links.linked_members(owner([group('a',[light]),group('b',[light])])),['light'])
    def test_two_independent_affine_bases(self):
        g={'nodes':{'uv':{'type':'texcoord','parameters':{'uv_map':'UV A'}},
          'scale':{'type':'multiply','parameters':{'in2':[2,3,1]},'inputs':{'in1':'uv'}},
          'rotate':{'type':'rotate2d','parameters':{'amount':90},'inputs':{'in':'scale'}},
          'other':{'type':'texcoord','parameters':{'uv_map':'UV B'}}}}
        a=graph_coordinates.descriptor('rotate',g);b=graph_coordinates.descriptor('other',g)
        self.assertEqual(a['uv_map'],'UV A');self.assertEqual(b['uv_map'],'UV B')
        self.assertAlmostEqual(a['uv_matrix'][1],-3);self.assertAlmostEqual(a['uv_matrix'][3],2)
        self.assertNotEqual(a['coordinate_key'],b['coordinate_key'])
    def test_nonlinear_basis_not_misrepresented_as_affine(self):
        g={'nodes':{'uv':{'type':'texcoord'},'square':{'type':'multiply','inputs':{'in1':'uv','in2':'uv'}}}}
        self.assertIsNone(graph_coordinates.descriptor('square',g))

if __name__=='__main__':unittest.main()
