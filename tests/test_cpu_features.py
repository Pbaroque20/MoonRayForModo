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
