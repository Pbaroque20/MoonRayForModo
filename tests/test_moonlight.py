"""MoonLightIPR scene packing and change detection; run outside Modo, no GPU needed."""
import struct
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import moonlight_scene
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
        first,keys,warnings=moonlight_scene.pack(scene(),320,180,.2)
        self.assertEqual(first[:4],b'MLS7')
        self.assertEqual(struct.unpack_from('<2I',first,4),(320,180))
        self.assertEqual(len(keys),1)
        self.assertFalse(any('CylinderLight' in w for w in warnings))
        second,again,_=moonlight_scene.pack(scene(),320,180,.2,known=keys)
        self.assertEqual(again,keys)
        self.assertLess(len(second),len(first))

    def test_invalid_scenes_are_refused(self):
        bad=scene();bad['meshes'][0]['faces']=[[0,1,9]]
        with self.assertRaises(ValueError):moonlight_scene.pack(bad,320,180)
        ortho=scene();ortho['camera']['projection']='ortho'
        with self.assertRaises(ValueError):moonlight_scene.pack(ortho,320,180)
        with self.assertRaises(ValueError):moonlight_scene.pack(scene(),8,8)

    def test_unsupported_layers_are_reported(self):
        layered=scene()
        layered['materials']['red']['textures']={'specCol':{'kind':'constant','value':[1,1,1]}}
        _,_,warnings=moonlight_scene.pack(layered,320,180)
        self.assertTrue(any('specularColor' in w for w in warnings))

    def test_constant_rows_are_folded(self):
        from moonray_modo.moonlight_materials import Compiler
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
        plain,_,_=moonlight_scene.pack(scene(),320,180)
        lens=scene();lens['camera'].update(dof=True,f_stop=2.0,focus_distance=3.0,iris_blades=6)
        packed,_,warnings=moonlight_scene.pack(lens,320,180)
        self.assertEqual(len(packed),len(plain))
        self.assertNotEqual(packed,plain)
        self.assertFalse(any('depth of field' in w for w in warnings))
        moving=scene();moving['motion_steps']=[-.25,.25]
        moving['camera']['matrix_close']=[1,0,0,0,0,1,0,0,0,0,1,0,.5,1,5,1]
        moving['meshes'][0]['vertices_close']=[[x,y+.2,z] for x,y,z in moving['meshes'][0]['vertices']]
        blurred,keys,_=moonlight_scene.pack(moving,320,180)
        # The closing camera, two closing transforms and four closing vertices.
        self.assertEqual(len(blurred)-len(plain),40+2*48+48)
        self.assertNotEqual(keys,moonlight_scene.pack(scene(),320,180)[1])
        lit=scene();lit['meshes'][0].pop('instances');lit['meshes'][0].pop('instance_ids')
        lit['production']={'objects':{'quad':{'mesh_light':True,'light_intensity':5.0}}}
        still=scene();still['meshes'][0].pop('instances');still['meshes'][0].pop('instance_ids')
        emitting,_,warnings=moonlight_scene.pack(lit,320,180)
        self.assertEqual(len(emitting)-len(moonlight_scene.pack(still,320,180)[0]),4+80+4+2*36)
        self.assertFalse(any('mesh light' in w for w in warnings))

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
