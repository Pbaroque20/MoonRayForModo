"""MoonLight scene packing and change detection; run outside Modo, no GPU needed."""
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
        self.assertEqual(first[:4],b'MLS6')
        self.assertEqual(struct.unpack_from('<2I',first,4),(320,180))
        self.assertEqual(len(keys),1)
        self.assertTrue(any('CylinderLight' in w for w in warnings))
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
