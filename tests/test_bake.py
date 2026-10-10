"""Baking: a scene is rendered through a bake camera on one Modo mesh, which the scene's text names once it is written."""
import sys,types,unittest
from pathlib import Path
for name in ('modo','lx','lxifc','lxu'):sys.modules.setdefault(name,types.ModuleType(name))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import bake


class Bake(unittest.TestCase):
    def scene(self):
        square=[[0,0,0],[1,0,0],[1,0,1],[0,0,1]]
        return {'width':640,'height':360,'region':[0,0,.5,.5],
                'entities':[{'identity':'cam','name':'Fisheye','class':'FisheyeCamera','matrix':bake.IDENTITY,'parameters':{'modo_render_camera':True,'zoom':1.0}}],
                'meshes':[{'name':'Floor','identity':'floor','vertices':square,'faces':[[0,1,2,3]],'uvs':[[0,0],[1,0],[1,1],[0,1]]},
                          {'name':'Bare','identity':'bare','vertices':square,'faces':[[0,1,2,3]]}]}

    def test_the_scene_is_rendered_square_through_a_bake_camera_and_no_other(self):
        made=bake.scene(self.scene(),'Floor',1024,1002)
        self.assertEqual((made['width'],made['height']),(1024,1024))
        self.assertNotIn('region',made)
        cameras=[e for e in made['entities'] if e['parameters'].get('modo_render_camera')]
        self.assertEqual([e['class'] for e in cameras],['BakeCamera'])
        self.assertEqual((cameras[0]['parameters']['geometry'],cameras[0]['parameters']['udim']),('Floor',1002))
        # What it was made from is left as it was.
        self.assertTrue(self.scene()['entities'][0]['parameters']['modo_render_camera'])

    def test_a_mesh_with_flat_faces_is_given_their_normals(self):
        made=bake.scene(self.scene(),'Floor',512)
        floor=next(m for m in made['meshes'] if m['name']=='Floor')
        self.assertEqual(len(floor['normals']),4)
        for normal in floor['normals']:self.assertAlmostEqual(abs(normal[1]),1.0)
        self.assertNotIn('normals',next(m for m in made['meshes'] if m['name']=='Bare'))

    def test_the_mesh_is_named_in_the_text_once_the_meshes_are_known(self):
        meshes=self.scene()['meshes']
        lines=['local camera = BakeCamera("/modo/camera") {','  ["geometry"] = %s,'%bake.placeholder('floor'),'}']
        bake.resolve(lines,meshes)
        self.assertEqual(lines[1],'  ["geometry"] = RdlMeshGeometry("/modo/mesh/0"),')

    def test_what_cannot_be_baked_is_refused_in_plain_words(self):
        meshes=self.scene()['meshes']
        for name,word in (('bare','no UV map'),('nothing','needs a Modo mesh')):
            with self.assertRaises(ValueError) as raised:bake.resolve(['  ["geometry"] = %s,'%bake.placeholder(name)],meshes)
            self.assertIn(word,str(raised.exception))
        with self.assertRaises(ValueError):bake.scene(self.scene(),'Floor',500)
        with self.assertRaises(ValueError):bake.scene(self.scene(),'Floor',512,900)


if __name__=='__main__':unittest.main()
