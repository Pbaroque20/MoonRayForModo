import sys, types, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import incremental

MATRIX=[1.0,0,0,0, 0,1,0,0, 0,0,1,0, 2,3,4,1]


def item(identity,kind,supers=()):
    return SimpleNamespace(id=identity,type=kind,TestType=lambda wanted:wanted in supers)


class Rigid(unittest.TestCase):
    def check(self,items,snapshot=None,descriptors=None,deformers=()):
        scene=SimpleNamespace(iterItems=lambda:iter(items),item=lambda identity:{i.id:i for i in items}[identity],
                              items=lambda kind,superType=True:[i for i in items if i.type==kind or (kind=='deform' and i in deformers)])
        fake_lx=types.ModuleType('lx');fake_lx.service=SimpleNamespace(Scene=lambda:SimpleNamespace(ItemTypeLookup=lambda name:name))
        host=types.ModuleType('moonray_modo.host');host.world_matrix=lambda held:list(MATRIX)
        coordinates=types.ModuleType('moonray_modo.coordinates');coordinates.descriptors=lambda materials:descriptors or {}
        snapshot=snapshot or {'meshes':[{'identity':'sofa|tag|0','matrix':list(MATRIX)}],'materials':{}}
        with patch.dict(sys.modules,{'lx':fake_lx,'moonray_modo.host':host,'moonray_modo.coordinates':coordinates}):
            return incremental.rigid(scene,snapshot)

    def steady(self):
        return [item('sofa','mesh'),item('xf','translation'),item('lamp','photometryLight',('light',)),
                item('wood','imageMap',('textureLayer',)),item('skin','material.dw.DwaSkinMaterial'),item('rect','moonray.RectLight'),
                item('cam','camera'),item('scene','scene')]

    def test_a_scene_of_meshes_lights_and_shading_holds_still(self):
        self.assertTrue(self.check(self.steady()))

    def test_rigs_shears_channel_modifiers_and_mesh_instances_make_no_mesh_and_hold_still(self):
        # A car converted from another renderer: shears, schematic nodes, a camera match, a target, V-Ray's channel
        # modifiers and instanced tyres, each standing where its own item does. Each end of the shutter read it whole.
        rig=[item('shear','shear'),item('workspace','assembly'),item('node','schmNode'),item('match','CameraMatch'),
             item('target','targetLocator'),item('tyre2','meshInst'),item('invert','cmMathBasic'),item('turn','cmRevolve')]
        snapshot={'meshes':[{'identity':'sofa|tag|0','matrix':list(MATRIX),'instances':[list(MATRIX),list(MATRIX)],
                             'instance_ids':['sofa|-1','tyre2|0']}],'materials':{}}
        self.assertTrue(self.check(self.steady()+rig,snapshot))

    def test_a_deformer_or_an_unknown_kind_of_item_does_not(self):
        bend=item('bend','deform.bend')
        self.assertFalse(self.check(self.steady()+[bend],deformers=(bend,)))
        self.assertFalse(self.check(self.steady()+[item('sim','particleSim')]))
        self.assertFalse(self.check(self.steady()+[item('copies','replicator')]))

    def test_a_texture_projected_from_where_a_mesh_stands_does_not(self):
        self.assertFalse(self.check(self.steady(),descriptors={'a':{'projection':'world'}}))
        self.assertTrue(self.check(self.steady(),descriptors={'a':{'projection':'uv'}}))

    def test_a_mesh_away_from_its_item_or_generated_copies_do_not(self):
        moved=list(MATRIX);moved[12]=9.0
        self.assertFalse(self.check(self.steady(),{'meshes':[{'identity':'sofa|tag|0','matrix':moved}],'materials':{}}))
        self.assertFalse(self.check(self.steady(),{'meshes':[{'identity':'sofa|tag|0','matrix':list(MATRIX),'instances':[MATRIX]}],'materials':{}}))
        self.assertFalse(self.check(self.steady(),{'meshes':[{'identity':'sofa|tag|0','matrix':list(MATRIX)}],'extra_geometry':[{}],'materials':{}}))

    def test_where_modo_cannot_be_asked_it_does_not(self):
        broken=SimpleNamespace(id='x',type='mesh',TestType=None)
        self.assertTrue(self.check(self.steady()+[broken]))     # a STEADY kind is not asked further
        odd=SimpleNamespace(id='y',type='odd',TestType=lambda wanted:1/0)
        self.assertFalse(self.check(self.steady()+[odd]))

    def test_at_another_moment_a_mesh_is_where_its_item_then_is_and_one_unmoved_keeps_its_matrix(self):
        read=[1.0000001,0,0,0, 0,1,0,0, 0,0,1,0, 2,3,4,1]      # as Modo's render cache gave it, a hair from its item's
        snapshot={'meshes':[{'identity':'sofa|a|0','matrix':list(read)},{'identity':'lamp|a|0','matrix':list(read)}]}
        later={'sofa':list(MATRIX),'lamp':[1.0,0,0,0, 0,1,0,0, 0,0,1,0, 5,3,4,1]}
        host=types.ModuleType('moonray_modo.host');host.world_matrix=lambda held:list(later[held.id])
        scene=SimpleNamespace(item=lambda identity:SimpleNamespace(id=identity))
        with patch.dict(sys.modules,{'moonray_modo.host':host}):
            incremental.follow_items(scene,snapshot,{'sofa':list(MATRIX),'lamp':list(MATRIX)})
        self.assertEqual(snapshot['meshes'][0]['matrix'],read)
        self.assertEqual(snapshot['meshes'][1]['matrix'],later['lamp'])

    def test_at_another_moment_each_instance_is_where_its_own_item_then_is(self):
        # A tyre placed by its own mesh and by a mesh instance: the instance's item moves, the mesh's does not.
        read=[1.0000001,0,0,0, 0,1,0,0, 0,0,1,0, 2,3,4,1]
        frame=[{'identity':'tyre|a|0','matrix':list(read),'instances':[list(read),list(read)],'instance_ids':['tyre|-1','copy|0']}]
        snapshot={'meshes':[dict(mesh) for mesh in frame]}
        later={'tyre':list(MATRIX),'copy':[1.0,0,0,0, 0,1,0,0, 0,0,1,0, 7,3,4,1]}
        host=types.ModuleType('moonray_modo.host');host.world_matrix=lambda held:list(later[held.id])
        scene=SimpleNamespace(item=lambda identity:SimpleNamespace(id=identity))
        with patch.dict(sys.modules,{'moonray_modo.host':host}):
            self.assertEqual(sorted(incremental.item_matrices(scene,snapshot)),['copy','tyre'])
            incremental.follow_items(scene,snapshot,{'tyre':list(MATRIX),'copy':list(MATRIX)})
        self.assertEqual(snapshot['meshes'][0]['instances'],[read,later['copy']])
        # The frame's own list is left as it was read: the reading at the shutter's end has a list of its own.
        self.assertEqual(frame[0]['instances'],[read,read])

    def test_instances_not_each_named_are_not_followed(self):
        read=list(MATRIX)
        snapshot={'meshes':[{'identity':'tyre|a|0','matrix':list(read),'instances':[list(read),list(read)],'instance_ids':['tyre|-1']}]}
        host=types.ModuleType('moonray_modo.host');host.world_matrix=lambda held:[2.0,0,0,0, 0,2,0,0, 0,0,2,0, 0,0,0,1]
        scene=SimpleNamespace(item=lambda identity:SimpleNamespace(id=identity))
        with patch.dict(sys.modules,{'moonray_modo.host':host}):
            incremental.follow_items(scene,snapshot,{'tyre':list(MATRIX)})
        self.assertEqual(snapshot['meshes'][0]['instances'],[read,read])


if __name__=='__main__':
    unittest.main()
