"""Deferred standalone graph/MaterialX checks. No renderer or Modo is launched."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import nodes,materialx

class GraphChecks(unittest.TestCase):
    def test_overrides_preserve_base(self):
        graph=nodes.new(parameters={'roughness':.2})
        graph['overrides']=[{'node':'surface','enabled':True,'parameters':{'roughness':.8}}]
        self.assertEqual(nodes.validate(graph)['nodes']['surface']['parameters']['roughness'],.8)
        self.assertEqual(graph['nodes']['surface']['parameters']['roughness'],.2)
        graph['overrides'][0]['enabled']=False
        self.assertEqual(nodes.validate(graph)['nodes']['surface']['parameters']['roughness'],.2)

    def test_cycles_rejected(self):
        graph=nodes.new()
        graph['nodes'].update(a={'type':'multiply','inputs':{'in1':'b'}},b={'type':'multiply','inputs':{'in1':'a'}})
        graph['nodes']['surface']['inputs']['albedo']='a'
        with self.assertRaisesRegex(ValueError,'cycle'): nodes.validate(graph)

    def test_native_roundtrip(self):
        graph=nodes.new(parameters={'roughness':.35})
        graph['nodes']['tint']={'type':'constant','parameters':{'value':[.7,.2,.1]}}
        graph['nodes']['surface']['inputs']['albedo']='tint'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'material.mtlx';materialx.write(graph,path)
            restored=materialx.read(path)
        root=restored['nodes'][restored['root']]
        self.assertEqual(root['parameters']['roughness'],.35)
        self.assertEqual(restored['nodes'][root['inputs']['albedo']]['parameters']['value'],[.7,.2,.1])

    def test_export_rejects_type_mismatch_without_overwriting(self):
        graph=nodes.new()
        graph['nodes']['value']={'type':'constant','parameters':{'value':[.2,.2,.2]}}
        graph['nodes']['surface']['inputs']['roughness']='value'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'material.mtlx';path.write_text('keep',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'matching socket types'): materialx.write(graph,path)
            self.assertEqual(path.read_text(encoding='utf-8'),'keep')

    def test_image_filename_definition_type(self):
        graph=nodes.new()
        graph['nodes']['image']={'type':'image','parameters':{'file':'texture.png'}}
        graph['nodes']['surface']['inputs']['albedo']='image'
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'material.mtlx';materialx.write(graph,path)
            document=ET.parse(path).getroot()
        self.assertEqual(document.find("nodedef[@name='ND_moonray_image']/input[@name='file']").get('type'),'filename')

    def test_standard_surface_defaults_and_metal_tint(self):
        content="""<materialx version="1.38"><standard_surface name="surface" type="surfaceshader"><input name="base_color" type="color3" value="0.2,0.3,0.4"/><input name="emission" type="float" value="1"/></standard_surface><surfacematerial name="m" type="material"><input name="surfaceshader" type="surfaceshader" nodename="surface"/></surfacematerial></materialx>"""
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'material.mtlx';path.write_text(content,encoding='utf-8');graph=materialx.read(path)
        params=graph['nodes'][graph['root']]['parameters']
        self.assertEqual(params['metallic_color'],[.2,.3,.4])
        self.assertEqual(params['emission'],[1,1,1])
        self.assertEqual(params['roughness'],.2)

    def test_entities_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'bad.mtlx';path.write_text('<!DOCTYPE materialx><materialx/>',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'entities'): materialx.read(path)

if __name__=='__main__': unittest.main()
