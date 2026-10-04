"""Deferred checks for 0.3.21; do not run during implementation."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
import xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'kit/MoonRayForModo/python'))
from moonray_modo import asset_import,asset_library,nodes,coordinates,instance_motion,materialx_expand,materialx,native,rdla,material_bundle

class Compatibility0321(unittest.TestCase):
    def test_every_indexed_extension_has_a_route(self):
        for ext in asset_library.CATEGORIES:self.assertTrue(asset_import.action('asset'+ext),ext)
        self.assertEqual(asset_import.action('asset.moonmat.json'),'Assign material')
        self.assertEqual(asset_import.action('asset.exe'),'')
        with self.assertRaises(ValueError):asset_import.command_path('a} bad.obj')
    def test_shared_rotation_scale_stays_one_instancer(self):
        start=list(rdla.IDENTITY);end=list(start);end[0]=0;end[1]=2;end[4]=-2;end[5]=0
        mesh={'instances':[start,start],'instances_close':[end,end],'instance_ids':['a','b'],'identity':'source'}
        lines=[];instance_motion.emit(mesh,0,'',{'_paired_instance_motion':True},False,lines)
        text='\n'.join(lines)
        self.assertEqual(text.count('RdlInstancerGeometry('),1)
        self.assertIn('"xform_list_close"',text)
        legacy=[];instance_motion.emit(mesh,0,'',{},False,legacy)
        self.assertEqual('\n'.join(legacy).count('RdlInstancerGeometry('),2)
        bad=dict(mesh,instances_close=[end])
        with self.assertRaises(ValueError):instance_motion.emit(bad,0,'',{},False,[])
    def test_normal_bases_do_not_replace_each_other(self):
        graph=nodes.new();root=graph['nodes'][graph['root']]
        graph['nodes']['a']={'type':'normalmap','parameters':{'basis_mode':1,'uv_map':'uvA','basis_rotation':90}}
        graph['nodes']['b']={'type':'normalmap','parameters':{'basis_mode':1,'uv_map':'uvB','basis_scale':[-1,1]}}
        root.setdefault('inputs',{}).update(input_normal='a',independent_clearcoat_normal='b')
        descriptors=nodes.descriptors(graph)
        self.assertEqual({v['uv_map'] for v in descriptors},{'uvA','uvB'})
        self.assertEqual(len({v['coordinate_key'] for v in descriptors}),2)
        a=next(v for v in descriptors if v['uv_map']=='uvA')
        uv=coordinates.transform_uv(a,[[1,0]])[0]
        self.assertAlmostEqual(uv[0],0);self.assertAlmostEqual(uv[1],1)
    def test_materialx_target_selection(self):
        doc=ET.fromstring("""<materialx>
        <nodedef name="ND_custom" node="custom"><output name="out" type="color3"/></nodedef>
        <nodegraph name="generic" nodedef="ND_custom"><constant name="c" type="color3"><input name="value" type="color3" value="1,0,0"/></constant><output name="out" type="color3" nodename="c"/></nodegraph>
        <nodegraph name="native" nodedef="ND_custom" target="moonray"><constant name="c" type="color3"><input name="value" type="color3" value="0,1,0"/></constant><output name="out" type="color3" nodename="c"/></nodegraph>
        <custom name="use" type="color3" nodedef="ND_custom"/>
        </materialx>""")
        expanded=materialx_expand.expand(doc)
        alias=expanded.find("output[@name='use']")
        clone=expanded.find("nodegraph[@name='"+alias.get('nodegraph')+"']")
        self.assertEqual(clone.find('constant/input').get('value'),'0,1,0')
    def test_runtime_capability_rejects_tampered_geometry(self):
        import hashlib
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);hashes={}
            for name in ('RdlInstancerGeometry.dll','librendering_geom.dll'):
                (root/name).write_bytes(b'fixture');hashes[name]=hashlib.sha256(b'fixture').hexdigest()
            (root/'modo-instance-motion.json').write_text(json.dumps({'version':1,'sha256':hashes}))
            self.assertTrue(native.supports_paired_instance_motion(root))
            (root/'RdlInstancerGeometry.dll').write_bytes(b'changed fixture')
            self.assertFalse(native.supports_paired_instance_motion(root))
    def test_disabled_override_survives_bundle(self):
        with tempfile.TemporaryDirectory() as d:
            data={'name':'Disabled','settings':{'native_shader':'DwaBaseMaterial','native_parameters':{},'moonshine_override':False}}
            path=material_bundle.save('source',lambda _:data,Path(d)/'bundle')
            loaded=material_bundle.load(path)
            self.assertIs(loaded['materials'][loaded['root']]['settings']['moonshine_override'],False)

if __name__=='__main__':unittest.main()
