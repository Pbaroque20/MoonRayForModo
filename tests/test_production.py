"""Deferred pure-Python checks; not executed during implementation."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import rdla,nodes,outputs,cryptomatte,sequence_plan,scene_delta,assets,evaluated


def scene():
    return {'camera':{'matrix':[1,0,0,0,0,1,0,0,0,0,1,0,0,0,4,1],'focal_mm':50,'film_mm':36},
        'materials':{'':{'color':[.5,.5,.5],'roughness':.3}},
        'meshes':[{'name':'Triangle','identity':'mesh1','vertices':[[-1,-1,0],[1,-1,0],[0,1,0]],'faces':[[0,1,2]],'matrix':rdla.IDENTITY}],
        'lights':[{'identity':'key','kind':'DistantLight','color':[1,1,1],'intensity':1,'matrix':rdla.IDENTITY}]}

class ProductionTests(unittest.TestCase):
    def test_displacement_is_a_layer_assignment(self):
        value=scene();graph=nodes.new();graph['nodes']['offset']={'type':'NormalDisplacement','parameters':{'height':.1,'bound_padding':.2}};graph['displacement']='offset';value['materials']['']['node_graph']=graph
        text=rdla.scene_text(value)
        self.assertIn('NormalDisplacement(',text);self.assertIn('table.insert(a, displacements[tag])',text);self.assertIn('["mesh_resolution"]',text)
        graph['displacement']='surface'
        with self.assertRaises(ValueError):nodes.validate(graph)

    def test_light_links_shadow_sets_and_group_labels(self):
        value=scene();value['production']={'lights':{'key':{'label':'key','filter_enabled':True}},'objects':{'mesh1':{'link_enabled':True,'lights':['key'],'shadow_exclude':['key']}}}
        text=rdla.scene_text(value)
        self.assertIn('ShadowSet(',text);self.assertIn('IntensityLightFilter(',text);self.assertIn('["label"] = "key"',text)
        value['production']['objects']['mesh1']['lights']=['missing']
        with self.assertRaises(ValueError):rdla.scene_text(value)

    def test_crypto_manifest_primvar_and_precision(self):
        value=scene();value['custom_aovs']=[{'name':'ids','kind':'cryptomatte','precision':1}]
        text=rdla.scene_text(value,output_file='beauty.exr')
        self.assertIn('deep_id_attribute_names',text);self.assertIn('modo_object_id',text);self.assertIn('MurmurHash3_32',text)
        self.assertEqual(outputs.values(value['custom_aovs'])[0]['precision'],0)
        self.assertEqual(cryptomatte.hash32('foo'),0xf6a5c420)

    def test_native_curves_and_particles(self):
        value=scene();value['extra_geometry']=[{'kind':'curves','identity':'hair','name':'Hair','vertices':[[0,0,0],[0,1,0]],'counts':[2],'radii':[.02,0]}, {'kind':'points','identity':'points','name':'Points','vertices':[[1,0,0]],'radius':.1}]
        text=rdla.scene_text(value);self.assertIn('RdlCurveGeometry(',text);self.assertIn('RdlPointGeometry(',text)
        value['extra_geometry'][0]['counts']=[3]
        with self.assertRaises(ValueError):rdla.scene_text(value)

    def test_light_only_delta_remains_incremental(self):
        value=scene();a=rdla.scene_text(value);value['lights'][0]['intensity']=2;b=rdla.scene_text(value)
        delta=scene_delta.difference(a,b);self.assertIsNotNone(delta);self.assertNotIn('vertex_list',delta)

    def test_custom_outputs_collisions(self):
        with self.assertRaises(ValueError):outputs.values([{'name':'normal','kind':'material','expression':'normal'}])
        v=outputs.values([{'name':'velocity','kind':'motion'}])[0]
        self.assertEqual(outputs.attributes(v)['state_variable'],12)

    def test_sequence_reuses_matching_frames_and_rejects_changed_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'frame.000001.exr';path.write_bytes(b'\x76\x2f\x31\x01'+b'0'*64)
            manifest={'signature':'scene','first':1,'last':2,'step':1,'prefix':'frame','fps':24,'motion_blur':False,'frames':[{'frame':1,'sha256':assets.file_hash(path)}]}
            (Path(folder)/'moonray-sequence.json').write_text(json.dumps(manifest))
            pending,done=sequence_plan.plan(folder,1,2,1,'frame',24,False,True,False,'scene');self.assertEqual(pending,[2]);self.assertEqual(len(done),1)
            path.write_bytes(path.read_bytes()+b'changed')
            with self.assertRaises(ValueError):sequence_plan.plan(folder,1,2,1,'frame',24,False,True,False,'scene')

    def test_missing_assets_are_reported(self):
        entries=assets.inventory({'material':{'path':'C:/MoonRayMissingAsset/texture.<UDIM>.exr'}})
        self.assertEqual(len(entries),1);self.assertTrue(entries[0]['missing'])

if __name__=='__main__':unittest.main()
