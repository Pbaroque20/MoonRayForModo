"""Deferred numerical/export checks. These do not establish renderer parity."""
import copy
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'kit/MoonRayForModo/python'))
from moonray_modo import coordinates, rdla, textures
from moonray_modo.environment_layers import blend


def scene():
    return {'camera':{'matrix':rdla.IDENTITY,'focal_mm':35,'film_mm':36},
            'materials':{'':{'color':[.7,.4,.2], 'shader':'DwaBaseMaterial'}},
            'meshes':[{'name':'quad','vertices':[[-1,-1,-3],[1,-1,-3],[1,1,-3],[-1,1,-3]],
                       'faces':[[0,1,2,3]],'uvs':[[0,0],[1,0],[1,1],[0,1]]}]}


class Textures(unittest.TestCase):
    def test_nested_group_opacity_is_applied_once_at_each_boundary(self):
        from moonray_modo.compositing import Groups
        def mix(a,b,opacity,mask):
            weight=opacity*(1 if mask is None else mask)
            return a+(b-a)*weight
        groups=Groups({'diffCol':0.,'rough':.2,'groupMask':1.},mix)
        outer={'id':'outer','opacity':.5}
        inner={'id':'inner','opacity':.25}
        groups.select([outer])
        groups.current['diffCol']=.4; groups.used.add('diffCol')
        groups.select([outer,inner])
        groups.current['diffCol']=1.; groups.used.add('diffCol')
        current,used=groups.finish()
        self.assertAlmostEqual(current['diffCol'],.275)
        self.assertEqual(current['rough'],.2)
        self.assertEqual(used,{'diffCol'})

    def test_group_mask_does_not_leak_into_sibling_or_material_scope(self):
        from moonray_modo.compositing import Groups
        groups=Groups({'diffCol':0.,'rough':0.,'groupMask':.8},
                      lambda a,b,o,m:a+(b-a)*o*(1 if m is None else m))
        groups.select([{'id':'masked'}])
        groups.current.update(diffCol=1.,groupMask=.25)
        groups.used.update(('diffCol','groupMask'))
        groups.select([{'id':'sibling'}])
        groups.current['rough']=1.;groups.used.add('rough')
        current,used=groups.finish()
        self.assertEqual(current['diffCol'],.25)
        self.assertEqual(current['rough'],1.)
        self.assertEqual(current['groupMask'],.8)
        self.assertNotIn('groupMask',used)

    def test_group_rejects_invalid_opacity_and_non_normal_blend(self):
        from moonray_modo.compositing import Groups
        for group in ({'id':'x','opacity':float('nan')},
                      {'id':'x','opacity':-1},{'id':'x','blend':'multiply'}):
            with self.assertRaises(ValueError):
                Groups({'groupMask':1},None).select([group])

    def test_group_mask_is_consumed_by_exported_texture_scope(self):
        from moonray_modo.graph import bindings
        group={'id':'texture folder','opacity':.5}
        material={'color':[.1]*3,'layers':[
            {'kind':'constant','effect':'diffCol','value':[1,0,0],'groups':[group]},
            {'kind':'constant','effect':'groupMask','value':[.25]*3,'groups':[group]}]}
        lines=[]
        maps=bindings(material,0,lines)
        self.assertIn('diffuseColor',maps)
        self.assertNotIn('layerMask',maps)
        self.assertIn('["mask"] = bind(', '\n'.join(lines))
        self.assertIn('["opacity"] = 0.5', '\n'.join(lines))

    def test_affine_locator_inverse_and_rotation(self):
        transform = list(rdla.IDENTITY); transform[0]=2; transform[5]=3; transform[12]=7
        p = [2,-1,4]
        restored = coordinates.transform(coordinates.transform(p,transform),coordinates.inverse(transform))
        for a,b in zip(p,restored): self.assertAlmostEqual(a,b)
        result = coordinates.face({'rotation':math.pi/2},[[0,0,0]],[[1,.5]],rdla.IDENTITY)
        self.assertAlmostEqual(result[0][0],.5)
        self.assertAlmostEqual(result[0][1],1)

    def test_named_uv_sets_keep_distinct_corner_values(self):
        value = scene()
        value['meshes'][0]['uv_sets']={'front':[[0,0],[1,0],[1,1],[0,1]],
                                    'back':[[1,0],[0,0],[0,1],[1,1]]}
        text = rdla.scene_text(value)
        self.assertIn('"front"',text); self.assertIn('"back"',text)
        value['meshes'][0]['uv_sets']['front'].pop()
        with self.assertRaises(ValueError): rdla.scene_text(value)

    def test_udim_enumeration_ignores_unrelated_and_missing_tiles(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('paint.1001.png','paint.1003.png','paint.abc.png','other.1002.png'):
                (root/name).write_bytes(b'fixture')
            self.assertEqual(set(textures.source_tiles(root/'paint.<UDIM>.png')),{1001,1003})


class Materials(unittest.TestCase):
    def test_partial_subsurface_preserves_surface_component(self):
        value=scene(); value['materials'][''].update(subsurface_amount=.4,subsurface_distance=.02)
        text=rdla.scene_text(value)
        self.assertIn('DwaLayerMaterial',text)
        self.assertIn('["scattering_radius"] = 0,',text)
        self.assertIn('["mask"] = 0.4',text)

    def test_absorption_uses_logarithmic_extinction(self):
        value=scene(); value['materials'][''].update(transmission=1,transmission_color=[math.exp(-1)]*3,absorption_distance=2)
        text=rdla.scene_text(value)
        self.assertIn('["attenuation_color"] = Rgb(0.5, 0.5, 0.5)',text)
        self.assertIn('["transmission_color"] = Rgb(1, 1, 1)',text)

    def test_material_order_and_opacity(self):
        value=scene(); value['materials']['']['material_stack']=[{'color':[1,0,0]}, {'color':[0,1,0],'layer_opacity':.25}]
        text=rdla.scene_text(value)
        self.assertIn('["mask"] = 0.25',text)
        self.assertLess(text.index('Rgb(1, 0, 0)'),text.index('Rgb(0, 1, 0)'))


class Geometry(unittest.TestCase):
    def test_invalid_crease_rejected(self):
        value=scene(); value['meshes'][0].update(subdivision=True,creases=[[0,8,2]])
        with self.assertRaises(ValueError): rdla.scene_text(value)

    def test_crease_pairs_and_sharpness(self):
        value=scene(); value['meshes'][0].update(subdivision=True,creases=[[0,1,2],[1,2,5]])
        text=rdla.scene_text(value)
        self.assertIn('["subd_crease_indices"] = {0, 1, 1, 2}',text)
        self.assertIn('["subd_crease_sharpnesses"] = {2, 5}',text)


class Environments(unittest.TestCase):
    def test_linear_blend_is_not_gamma_encoded(self):
        self.assertEqual(blend([0]*3,[1]*3,'normal',.5),[.5]*3)
        self.assertEqual(blend([.25]*3,[.8]*3,'multiply',1),[.2]*3)
        self.assertEqual(blend([4]*3,[1]*3,'add',1),[5]*3)

    def test_daylight_finite_at_horizon_and_zenith(self):
        from moonray_modo.daylight import color
        for direction in ((1,0,0),(0,1,0),(0,-1,0)):
            result=color(direction,{'sun_direction':[0,1,0],'haze':1})
            self.assertTrue(all(math.isfinite(c) and c>=0 for c in result))


class Rendering(unittest.TestCase):
    def test_orthographic_and_region(self):
        value=scene(); value['camera'].update(projection='ortho',ortho_width=4)
        value['region']=[.25,.125,.75,.5]
        text=rdla.scene_text(value,128,128)
        self.assertIn('OrthographicCamera',text)
        self.assertNotIn('["focal"]',text)
        self.assertIn('["sub_viewport"] = {32, 64, 96, 112}',text)

    def test_motion_endpoints_exported(self):
        value=scene(); value['motion_steps']=[-.25,.25]
        value['camera']['matrix_close']=list(rdla.IDENTITY)
        value['camera']['matrix_close'][12]=1
        value['meshes'][0]['vertices_close']=[[x+.2,y,z] for x,y,z in value['meshes'][0]['vertices']]
        text=rdla.scene_text(value)
        self.assertIn('blur(',text); self.assertIn('["vertex_list_1"]',text)
        self.assertIn('["enable_motion_blur"] = true',text)


if __name__=='__main__': unittest.main()
