"""Deferred exporter and MaterialX integration cases. Not run by installation."""
import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import cryptomatte,outputs,rdla,materialx

class Compatibility0326(unittest.TestCase):
    def scene(self):
        return {'camera':{'matrix':rdla.IDENTITY,'film_mm':36,'focal_mm':50},'lights':[],
          'materials':{'a':{'name':'Red','color':[1,0,0]},'b':{'name':'Blue','color':[0,0,1]}},
          'meshes':[{'identity':'mesh1','name':'Two faces','material':'a','face_materials':['a','b'],
                     'vertices':[[0,0,0],[1,0,0],[0,1,0],[1,1,0]],'faces':[[0,1,2],[1,3,2]],'matrix':rdla.IDENTITY}],
          '_crypto_categories':True,'custom_aovs':[{'name':'Mask_'+c,'kind':'cryptomatte','category':c} for c in ('object','material','asset')]}
    def test_three_categories_and_metadata(self):
        text=rdla.scene_text(self.scene(),16,16,1,.1,'test.exr')
        for category in ('object','material','asset'):
            self.assertIn('modo_'+category+'_id',text)
            self.assertIn('crypto_'+category,text)
            self.assertIn('Metadata("/modo/outputMetadata/'+category+'")',text)
        for index in range(3):self.assertIn('["cryptomatte_id_channel"] = '+str(index),text)
    def test_incompatible_runtime_and_volume_fail_explicitly(self):
        scene=self.scene();scene.pop('_crypto_categories')
        with self.assertRaisesRegex(ValueError,'category-enabled'):rdla.scene_text(scene,16,16,1,0,'test.exr')
        scene['_crypto_categories']=True;scene['extra_geometry']=[{'kind':'vdb'}]
        with self.assertRaisesRegex(ValueError,'Volume Cryptomatte'):rdla.scene_text(scene,16,16,1,0,'test.exr')
    def test_instance_material_ids_inherit_prototype(self):
        scene=self.scene();mesh=dict(scene['meshes'][0],instance_ids=['i1','i2'])
        lines=[];values=cryptomatte.userdata_set(mesh,lines,scene,instances=True)
        self.assertEqual(len(values),2)
        self.assertNotIn('modo_material_id','\n'.join(lines))
        self.assertIn('modo_object_id','\n'.join(lines));self.assertIn('modo_asset_id','\n'.join(lines))
    def test_duplicate_category_or_part_is_rejected(self):
        entries=self.scene()['custom_aovs']
        with self.assertRaises(ValueError):outputs.values(entries+[dict(entries[0],name='Again')])
        entries[0]['part']=entries[1]['part']='same'
        with self.assertRaises(ValueError):outputs.values(entries)
    def test_checkpoint_includes_required_resume_buffers(self):
        scene=self.scene();scene['_recovery']={'file':'checkpoint.exr','guides':{},'minutes':.1,'resume':False}
        text=rdla.scene_text(scene,16,16,4,.1,'test.exr')
        for name,result in (('weight',11),('beauty_aux',12),('alpha_aux',14)):
            self.assertIn('RenderOutput("/modo/aov/__recovery_'+name+'")',text)
            self.assertIn('["result"] = '+str(result),text)
        self.assertIn('["file_part"] = "__modo_main"',text)
        self.assertIn('["file_part"] = "crypto_material"',text)
        scene['aovs']=['sample_count']
        text=rdla.scene_text(scene,16,16,4,.1,'test.exr')
        self.assertNotIn('RenderOutput("/modo/aov/__recovery_weight")',text)

    def test_materialx_geometric_graph(self):
        source="""<materialx version="1.39"><position name="p" type="vector3"><input name="space" type="string" value="world"/></position>
        <geompropvalue name="mask" type="float"><input name="geomprop" type="string" value="weight"/><input name="default" type="float" value="0.5"/></geompropvalue>
        <rgbtohsv name="h" type="color3"><input name="in" type="color3" nodename="p"/></rgbtohsv>
        <hsvtorgb name="c" type="color3"><input name="in" type="color3" nodename="h"/></hsvtorgb>
        <standard_surface name="s" type="surfaceshader"><input name="base_color" type="color3" nodename="c"/><input name="metalness" type="float" nodename="mask"/></standard_surface>
        <surfacematerial name="m" type="material"><input name="surfaceshader" type="surfaceshader" nodename="s"/></surfacematerial></materialx>"""
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'graph.mtlx';path.write_text(source,encoding='utf-8');graph=materialx.read(path)
        kinds={n['type'] for n in graph['nodes'].values()}
        self.assertTrue({'AttributeMap','TransformSpaceMap','RgbToHsvMap','HsvToRgbMap','DwaBaseMaterial'}<=kinds)

if __name__=='__main__':unittest.main()
