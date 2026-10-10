"""MoonLightIPR scene packing and change detection; run outside Modo, no GPU needed."""
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import moonlightipr_scene
from moonray_modo.scene_digest import digest

def scene():
    return {'camera':{'matrix':[1,0,0,0,0,1,0,0,0,0,1,0,0,1,5,1],'focal_mm':50.0,'film_mm':36.0},
            'materials':{'':{'color':[.5,.5,.5],'roughness':.6},'red':{'color':[.8,.1,.1],'roughness':.3}},
            'meshes':[{'name':'Quad','identity':'quad','vertices':[[-1,0,-1],[1,0,-1],[1,0,1],[-1,0,1]],'faces':[[0,3,2,1]],
                       'face_materials':['red'],'instances':[[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1],[1,0,0,0,0,1,0,0,0,0,1,0,3,0,0,1]],'instance_ids':['a','b']}],
            'lights':[{'kind':'DistantLight','identity':'sun','name':'Sun','color':[1,1,1],'intensity':2.0,'angle':1.0,'matrix':[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]},
                      {'kind':'CylinderLight','identity':'tube','name':'Tube','color':[1,1,1],'intensity':1.0}],
            'environments':[]}

class PackTests(unittest.TestCase):
    def test_known_meshes_are_sent_once(self):
        first,keys,warnings=moonlightipr_scene.pack(scene(),320,180,.2)
        self.assertEqual(first[:4],b'MLSA')
        self.assertEqual(struct.unpack_from('<2I',first,4),(320,180))
        self.assertEqual(len(keys),1)
        self.assertFalse(any('CylinderLight' in w for w in warnings))
        second,again,_=moonlightipr_scene.pack(scene(),320,180,.2,known=keys)
        self.assertEqual(again,keys)
        self.assertLess(len(second),len(first))

    def test_invalid_scenes_are_refused(self):
        bad=scene();bad['meshes'][0]['faces']=[[0,1,9]]
        with self.assertRaises(ValueError):moonlightipr_scene.pack(bad,320,180)
        ortho=scene();ortho['camera']['projection']='ortho'
        with self.assertRaises(ValueError):moonlightipr_scene.pack(ortho,320,180)
        with self.assertRaises(ValueError):moonlightipr_scene.pack(scene(),8,8)

    def test_unsupported_layers_are_reported(self):
        layered=scene()
        layered['materials']['red']['textures']={'specCol':{'kind':'constant','value':[1,1,1]}}
        _,_,warnings=moonlightipr_scene.pack(layered,320,180)
        self.assertTrue(any('specularColor' in w for w in warnings))

    def test_constant_rows_are_folded(self):
        from moonray_modo.moonlightipr_materials import Compiler
        row=lambda name,color,opacity:{'name':name,'base_layer_id':name,'shader':'DwaBaseMaterial','color':color,'raw_color':color,'roughness':.5,
                                       'layer_opacity':opacity,'layer_blend':'normal','material_groups':[],'layers':[]}
        compiler=Compiler()
        record=compiler.material({'material_stack':[row('under',[1,0,0],1.0),row('over',[0,0,1],.5)]},'stack')
        self.assertEqual(compiler.layers,[])
        color=struct.unpack_from('<3f',record)
        for value,expected in zip(color,(.5,0,.5)):self.assertAlmostEqual(value,expected,places=6)
        # A gradient reads channels part way up the stack, so nothing may be folded beneath it.
        ramp={'input':'driverA','positions':[0,1],'colors':[[0,0,0],[1,1,1]]}
        compiler=Compiler()
        top=dict(row('over',[0,0,1],.5),layers=[{'kind':'gradient','effect':'diffCol','gradient':ramp,'groups':[]}])
        compiler.material({'material_stack':[row('under',[1,0,0],1.0),top]},'stack')
        self.assertTrue(compiler.layers)

    def test_lens_motion_and_mesh_lights_are_packed(self):
        plain,_,_=moonlightipr_scene.pack(scene(),320,180)
        lens=scene();lens['camera'].update(dof=True,f_stop=2.0,focus_distance=3.0,iris_blades=6)
        packed,_,warnings=moonlightipr_scene.pack(lens,320,180)
        self.assertEqual(len(packed),len(plain))
        self.assertNotEqual(packed,plain)
        self.assertFalse(any('depth of field' in w for w in warnings))
        moving=scene();moving['motion_steps']=[-.25,.25]
        moving['camera']['matrix_close']=[1,0,0,0,0,1,0,0,0,0,1,0,.5,1,5,1]
        moving['meshes'][0]['vertices_close']=[[x,y+.2,z] for x,y,z in moving['meshes'][0]['vertices']]
        blurred,keys,_=moonlightipr_scene.pack(moving,320,180)
        # The closing camera, two closing transforms and four closing vertices.
        self.assertEqual(len(blurred)-len(plain),40+2*48+48)
        self.assertNotEqual(keys,moonlightipr_scene.pack(scene(),320,180)[1])
        lit=scene();lit['meshes'][0].pop('instances');lit['meshes'][0].pop('instance_ids')
        lit['production']={'objects':{'quad':{'mesh_light':True,'light_intensity':5.0}}}
        still=scene();still['meshes'][0].pop('instances');still['meshes'][0].pop('instance_ids')
        emitting,_,warnings=moonlightipr_scene.pack(lit,320,180)
        self.assertEqual(len(emitting)-len(moonlightipr_scene.pack(still,320,180)[0]),4+80+4+4+4+2*36)
        self.assertFalse(any('mesh light' in w for w in warnings))

class EntityTests(unittest.TestCase):
    def items(self):
        at=lambda x,y,z:[1,0,0,0,0,1,0,0,0,0,1,0,x,y,z,1]
        return [{'identity':'env','name':'Sky','class':'EnvLight','matrix':at(0,0,0),'parameters':{'color':[.2,.3,.4]}},
                {'identity':'rod','name':'Rod','class':'RodLightFilter','matrix':at(0,1,0),'parameters':{}},
                {'identity':'key','name':'Key','class':'SpotLight','matrix':at(0,4,0),'parameters':{'intensity':5.0,'light_filters':['Rod']}},
                {'identity':'fog','name':'Fog','class':'BaseVolume','parameters':{}},
                {'identity':'box','name':'Box','class':'BoxGeometry','matrix':at(1,0,0),'parameters':{'modo_material':'red','modo_volume':'Fog'}},
                {'identity':'eye','name':'Eye','class':'FisheyeCamera','matrix':at(0,1,5),'parameters':{'modo_render_camera':True}}]

    def test_values_are_checked_against_the_schema(self):
        from moonray_modo import entities
        self.assertEqual(len(entities.classes()),30)
        self.assertEqual(entities.validate('SpotLight',{'outer_cone_angle':40})['outer_cone_angle'],40.0)
        for name,parameters in (('SpotLight',{'outer_cone_angle':'wide'}),('SpotLight',{'no_such':1}),('NoSuchLight',{}),
                                ('EnvLight',{'color':[1,1]}),('EnvLight',{'visible_in_camera':7})):
            with self.assertRaises(ValueError):entities.validate(name,parameters)

    def test_items_reach_the_moonray_scene(self):
        from moonray_modo import rdla
        with_items=scene();with_items['entities']=self.items();with_items['lights']=with_items['lights'][:1]
        text=rdla.scene_text(with_items,320,180,1,0.0)
        self.assertIn('local camera = FisheyeCamera("/modo/camera") {',text)
        self.assertNotIn('PerspectiveCamera("/modo/camera")',text)
        self.assertIn('["light_filters"] = {RodLightFilter("/modo/entity/rod")}',text)
        self.assertIn('table.insert(lights, SpotLight("/modo/entity/key"))',text)
        # MoonRay fills a mesh with a volume but not its own box, so a box that holds one goes as a mesh.
        self.assertIn('table.insert(assignments, {RdlMeshGeometry("/modo/entity/box"), "", materials["red"], lightSet, BaseVolume("/modo/entity/fog")})',text)
        self.assertLess(text.index('table.insert(lights, EnvLight("/modo/entity/env"))'),text.index('local lightSet'))
        # A volume shader has no place, so it must not be given a transform.
        self.assertNotIn('node_xform',text[text.index('BaseVolume("/modo/entity/fog") {'):text.index('BoxGeometry("/modo/entity/box") {')])
        broken=scene();broken['entities']=[dict(self.items()[2])];broken['lights']=broken['lights'][:1]
        with self.assertRaises(ValueError):rdla.scene_text(broken,320,180,1,0.0)

    def test_moonlightipr_draws_what_it_can_and_names_the_rest(self):
        with_items=scene();with_items['entities']=self.items()
        packed,_,warnings=moonlightipr_scene.pack(with_items,320,180)
        self.assertGreater(len(packed),len(moonlightipr_scene.pack(scene(),320,180)[0]))
        for expected in ('does not apply RodLightFilter (Rod on Key)','does not show volumes (Box)','BaseVolume (Fog)'):
            self.assertTrue(any(expected in w for w in warnings),expected)
        # The fisheye camera set to render is what MoonLightIPR looks through, so nothing is said of it.
        self.assertFalse(any('Eye' in w for w in warnings))

    def test_filters_a_light_picture_and_mesh_lights_reach_moonlightipr(self):
        at=lambda x,y,z:[1,0,0,0,0,1,0,0,0,0,1,0,x,y,z,1]
        plain=scene();plain['meshes'][0].pop('instances');plain['meshes'][0].pop('instance_ids')
        light=lambda **more:{'identity':'key','name':'Key','class':'SphereLight','matrix':at(0,4,0),'parameters':dict({'intensity':5.0},**more)}
        bare=dict(plain,entities=[light()])
        base,_,_=moonlightipr_scene.pack(bare,320,180)
        filters=[{'identity':'d','name':'Decay','class':'DecayLightFilter','parameters':{'falloff_far':True,'far_start':2.0,'far_end':5.0}},
                 {'identity':'t','name':'Tint','class':'IntensityLightFilter','parameters':{'color':[1.0,.5,.25]}},
                 {'identity':'r','name':'Ramp','class':'ColorRampLightFilter','matrix':at(0,0,0),'parameters':{}}]
        packed,_,warnings=moonlightipr_scene.pack(dict(plain,entities=filters+[light(light_filters=['Decay','Tint','Ramp'])]),320,180)
        self.assertFalse(any('filter' in w.lower() for w in warnings),warnings)
        # Two filters of 80 bytes each for the renderer; the tint is folded into the light. The ramp adds an image.
        self.assertGreater(len(packed)-len(base),160)
        # A mesh light item makes the mesh it names emit, as Object controls would.
        lit,_,warnings=moonlightipr_scene.pack(dict(plain,entities=[{'identity':'m','name':'Glow','class':'MeshLight','parameters':{'geometry':'Quad','intensity':3.0}}]),320,180)
        by_controls,_,_=moonlightipr_scene.pack(dict(plain,production={'objects':{'quad':{'mesh_light':True,'light_color':[1.0,1.0,1.0],'light_intensity':3.0}}}),320,180)
        self.assertEqual(lit,by_controls)
        self.assertFalse(warnings,warnings)
        _,_,warnings=moonlightipr_scene.pack(dict(plain,entities=[{'identity':'m','name':'Glow','class':'MeshLight','parameters':{'geometry':'Nothing'}}]),320,180)
        self.assertTrue(any('needs the name of one Modo mesh' in w for w in warnings),warnings)

    def test_a_moonray_environment_can_replace_modos(self):
        from moonray_modo import rdla
        sky={'kind':'constant','name':'Sky','intensity':1.0,'zenith':[.2,.3,.4],'nadir':[.2,.3,.4]}
        env=lambda **more:{'identity':'e','name':'Env','class':'EnvLight','parameters':dict({'color':[1.0,.5,.25]},**more)}
        base=scene();base['lights']=base['lights'][:1];base['environments']=[sky]
        beside=rdla.scene_text(dict(base,entities=[env()]),320,180,1,.15)
        instead=rdla.scene_text(dict(base,entities=[env(modo_replace_environment=True)]),320,180,1,.15)
        self.assertIn('EnvLight("/modo/environment")',beside);self.assertIn('EnvLight("/modo/environment/scene/0")',beside)
        self.assertNotIn('EnvLight("/modo/environment")',instead);self.assertNotIn('/modo/environment/scene/',instead)
        self.assertIn('EnvLight("/modo/entity/e")',instead);self.assertNotIn('modo_replace_environment',instead)
        a,_,_=moonlightipr_scene.pack(dict(base,entities=[env()]),320,180,.15)
        b,_,_=moonlightipr_scene.pack(dict(base,entities=[env(modo_replace_environment=True)]),320,180,.15)
        self.assertNotEqual(a,b)

class DigestTests(unittest.TestCase):
    def test_follows_content_not_identity(self):
        a,b=scene(),scene()
        self.assertEqual(digest(a,'x'),digest(b,'x'))
        self.assertNotEqual(digest(a,'x'),digest(a,'y'))
        b['meshes'][0]['vertices'][2][1]=.25
        self.assertNotEqual(digest(a,'x'),digest(b,'x'))
        moved=scene();moved['camera']['matrix'][12]=2
        self.assertNotEqual(digest(a,'x'),digest(moved,'x'))

if __name__=='__main__':unittest.main()
