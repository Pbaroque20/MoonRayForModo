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
    def test_image_channel_selection_and_alpha_only_are_explicit(self):
        from moonray_modo.graph import bindings
        for channel,component in [('red',0),('green',1),('blue',2),('only',None)]:
            material={'color':[1]*3,'layers':[{'kind':'imageMap','effect':'rough',
                'path':'packed.png','image_channel':channel}]}
            lines=[]
            with patch('moonray_modo.textures.prepare',return_value='packed.tx'):
                result=bindings(material,0,lines)
            self.assertIn('roughness',result)
            text='\n'.join(lines)
            self.assertIn('["alpha_only"] = true',text)
            if component is not None:
                self.assertIn('["component"] = '+str(component),text)
            else:
                self.assertNotIn('["mode"] = 7',text)
                self.assertNotIn('["blend"] = 5',text)

    def test_projection_seams_are_corrected_per_face(self):
        descriptor={'projection':'spherical','locator_matrix':rdla.IDENTITY}
        vertices=[[.1,0,-1],[.2,1,-1],[.3,0,-1],[-.1,0,-1],[-.2,1,-1],[-.3,0,-1]]
        faces=[[0,1,2],[3,4,5]]
        values=coordinates.mesh_corners(descriptor,vertices,faces,[],rdla.IDENTITY)
        expected=sum([coordinates.face(descriptor,[vertices[i] for i in face],[],rdla.IDENTITY) for face in faces],[])
        self.assertEqual(values,expected)
        self.assertTrue(all(u<.5 for u,v in values[3:]))

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
        self.assertAlmostEqual(result[0][0],-.5)
        self.assertAlmostEqual(result[0][1],1)

    def test_mixed_repeat_modes_are_sampled_after_uv_interpolation(self):
        from moonray_modo.graph import bindings
        material={'color':[.1]*3,'layers':[{'kind':'imageMap','effect':'diffCol',
            'path':'fixture.png','tile_u':'mirror','tile_v':'reset','use_alpha':True,
            'coordinate_key':'unwrapped_uv'}]}
        lines=[]
        with patch('moonray_modo.textures.prepare',return_value='fixture.tx'):
            bindings(material,0,lines)
        text='\n'.join(lines)
        self.assertIn('["mode"] = 5',text)
        self.assertIn('["mode"] = 6',text)
        self.assertIn('["tile_u"] = 2',text)
        self.assertIn('["tile_v"] = 3',text)
        self.assertIn('["wrap_around"] = false',text)
        self.assertIn('["mask"] = bind(',text)

    def test_udim_repeat_keeps_integer_tile_address(self):
        from moonray_modo.graph import bindings
        layer={'kind':'imageMap','effect':'diffCol','path':'tile.<UDIM>.png',
               'tile_u':'repeat','tile_v':'repeat','coordinate_key':'udim_uv'}
        material={'color':[1]*3,'layers':[layer]}
        lines=[]
        with patch('moonray_modo.textures.prepare',return_value='tile.<UDIM>.tx'):
            bindings(material,0,lines)
            self.assertNotIn('["mode"] = 5','\n'.join(lines))
            layer['tile_u']='mirror'
            with self.assertRaises(ValueError): bindings(material,0,[])

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
    def test_subsurface_maps_route_to_moonshine_and_mask_surface_mix(self):
        value=scene()
        value['materials'][''].update(shader='',subsurface_amount=0,subsurface_distance=.02,
            layers=[{'kind':'constant','effect':'subsAmount','value':[.35]*3},
                    {'kind':'constant','effect':'subsColor','value':[1,.2,.1]}])
        text=rdla.scene_text(value)
        self.assertIn('DwaBaseMaterial',text)
        self.assertIn('/sss_mix',text)
        self.assertIn('["scattering_color"] = bind(',text)
        self.assertIn('["mask"] = bind(',text)
        self.assertNotIn('["subsurfaceAmount"]',text)

    def test_moonshine_model_and_direction_controls(self):
        value=scene()
        value['materials'][''].update(subsurface_amount=1,subsurface_distance=.02,
            subsurface_model=2,anisotropy_angle=math.pi/2,sss_input_normal=True,
            sss_resolve_self_intersections=False)
        text=rdla.scene_text(value)
        self.assertIn('["bssrdf"] = 2',text)
        self.assertIn('["enable_sss_input_normal"] = true',text)
        self.assertIn('["resolve_self_intersections"] = false',text)
        from moonray_modo.material_settings import validate
        for key,bad in [('subsurface_model',1.5),('subsurface_model',3),('anisotropy_angle',float('nan'))]:
            with self.assertRaises(ValueError): validate(key,bad)

    def test_layered_common_absorption_is_only_applied_in_volume(self):
        value=scene()
        glass={'color':[1]*3,'transmission':1,'absorption_distance':2,
               'transmission_color':[math.exp(-1)]*3}
        value['materials']['']['material_stack']=[glass,dict(glass,roughness=.4,layer_opacity=.5)]
        text=rdla.scene_text(value)
        self.assertIn('["attenuation_color"] = Rgb(0.5, 0.5, 0.5)',text)
        self.assertEqual(text.count('["transmission_color"] = Rgb(1, 1, 1)'),2)

    def test_incompatible_active_interiors_rejected_but_hidden_layer_ignored(self):
        from moonray_modo.absorption import medium
        a={'transmission':1,'absorption_distance':1}
        b={'transmission':1,'absorption_distance':2,'layer_opacity':.5}
        with self.assertRaises(ValueError): medium({'material_stack':[a,b]})
        b['layer_opacity']=1
        self.assertIs(medium({'material_stack':[a,b]}),b)
        b['layer_opacity']=0
        self.assertIs(medium({'material_stack':[a,b]}),a)

    def test_transmission_group_mask_is_retained_for_volume_mapping(self):
        from moonray_modo.absorption import color_layers,surface
        material={'transmission':1,'absorption_distance':1,'layers':[
            {'effect':'tranColor','groups':[{'id':'g'}]},
            {'effect':'groupMask','groups':[{'id':'g'}]}, {'effect':'rough'}]}
        self.assertEqual([entry['effect'] for entry in color_layers(material)],['tranColor','groupMask'])
        self.assertEqual([entry['effect'] for entry in surface(material)['layers']],['groupMask','rough'])

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
    def test_evaluated_projections_expand_instances_but_uvs_share(self):
        from moonray_modo import evaluated
        shifted=list(rdla.IDENTITY);shifted[12]=2
        segment={'vertices':[[0,0,0],[1,0,0],[0,1,0]],'faces':[[0,1,2]],
                 'normals':[],'uv_sets':[[[0,0],[1,0],[0,1]]]}
        data={'prototypes':{'1':{'features':[{'type':0x54585556,'name':'Texture'}],'segments':[segment]}},
              'surfaces':[{'source_id':1,'source_item':'mesh','material':'m','layers':[],
                           'visibility':[True]*6,'matrix':matrix,'instance_index':i}
                          for i,matrix in enumerate((rdla.IDENTITY,shifted))]}
        descriptor={'projection':'planar','locator_matrix':rdla.IDENTITY,'coordinate_key':'projected'}
        materials={'m':{'layers':[descriptor]}}
        values=evaluated.meshes(data,materials,[])
        self.assertEqual(len(values),2)
        self.assertNotEqual(values[0]['identity'],values[1]['identity'])
        self.assertAlmostEqual(values[1]['uv_sets']['projected'][0][0]-values[0]['uv_sets']['projected'][0][0],2)
        materials['m']['layers']=[{'projection':'uv','uv_map':'Texture','coordinate_key':'uv'}]
        values=evaluated.meshes(data,materials,[])
        self.assertEqual(len(values),1)
        self.assertEqual(len(values[0]['instances']),2)

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
