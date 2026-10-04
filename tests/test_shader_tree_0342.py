"""Deferred Shader Tree checks. Run explicitly; never launched by installation."""
import os, struct, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'kit/MoonRayForModo/python'))
from moonray_modo import graph, moonshine, procedurals, textures, native_light_links, environment_layers

class ShaderTree0342(unittest.TestCase):
    def test_layer_mask_targets_one_row(self):
        material={'color':[.5]*3,'layers':[
            {'identity':'mask','kind':'constant','effect':'layerMask','mask_target':'red','value':[0]*3},
            {'identity':'red','kind':'constant','effect':'diffCol','value':[1,0,0]},
            {'identity':'blue','kind':'constant','effect':'diffCol','value':[0,0,1]}]}
        lines=[];out=graph.bindings(material,0,lines)
        text='\n'.join(lines)
        self.assertEqual(text.count('["mask"]'),1)
        self.assertIn('diffuseColor',out);self.assertNotIn('singleLayerMask',out)
    def test_mask_does_not_jump_over_skipped_target(self):
        lines=[]
        graph.bindings({'layers':[{'kind':'constant','effect':'layerMask','mask_target':'missing','value':[0]*3},
                                 {'identity':'other','kind':'constant','effect':'rough','value':[.8]*3}]},0,lines)
        self.assertNotIn('["mask"]','\n'.join(lines))
    def test_layer_mask_on_group_applies_to_each_channel(self):
        g=[{'id':'group','blend':'normal','opacity':1}]
        lines=[];graph.bindings({'layers':[
            {'kind':'constant','effect':'layerMask','mask_target':'group','value':[.3]*3},
            {'identity':'color','kind':'constant','effect':'diffCol','value':[1,0,0],'groups':g},
            {'identity':'rough','kind':'constant','effect':'rough','value':[.8]*3,'groups':g}]},0,lines)
        self.assertEqual('\n'.join(lines).count('["mask"]'),2)
    def test_clearcoat_normal_is_independent(self):
        lines=[]
        with patch.object(textures,'prepare',return_value='fixture.tx'):
            maps=graph.bindings({'layers':[{'kind':'imageMap','effect':'normalCoat','path':'fixture.png','image_channel':'ignore','blend':'normalblend'}]},0,lines)
        self.assertIn('coatNormal',maps);self.assertNotIn('normal',maps)
        moonshine.emit({'color':[.5]*3},'fixture',0,maps,lines)
        text='\n'.join(lines)
        self.assertIn('"independent_clearcoat_normal"',text)
        self.assertIn('"use_independent_clearcoat_normal"] = true',text)
    def test_diffuse_roughness_binding(self):
        lines=[];maps=graph.bindings({'layers':[{'kind':'constant','effect':'diffRough','value':[.6]*3}]},0,lines)
        moonshine.emit({'color':[.5]*3},'fixture',0,maps,lines)
        self.assertIn('"diffuse_roughness"] = bind','\n'.join(lines))
    def test_procedural_repeat_and_alpha(self):
        for kind,patterns in [('grid',('line','square','triangle','hexagon')),('dots',('square','triangle','hexagon'))]:
            for pattern in patterns:
                data=dict(kind=kind,pattern=pattern,width=.3,transition=.02,bias=.5,gain=.5,color1=[1,0,0],color2=[0,0,1],alpha1=.2,alpha2=.8)
                a=procedurals.sample(data,.13,.27);b=procedurals.sample(data,1.13,1.27)
                for x,y in zip(a[0],b[0]):self.assertAlmostEqual(x,y)
                self.assertAlmostEqual(a[1],b[1]);self.assertTrue(.2<=a[1]<=.8)
    def test_environment_layer_mask_and_group_opacity(self):
        group=[{'id':'group','blend':'normal','opacity':.5}]
        # Environment capture is top-first; the baker composites bottom-first.
        environment={'layers':[
            {'kind':'color','color':[1,0,0],'layer_identity':'red','groups':group},
            {'kind':'color','color':[0,0,0],'effect':'layerMask','mask_target':'red','groups':group},
            {'kind':'color','color':[0,0,1],'layer_identity':'blue'}]}
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ,{'LOCALAPPDATA':folder}), patch.object(textures,'prepare',side_effect=lambda path,*a,**kw:str(path)):
            path=environment_layers.texture(environment,width=1,height=1)
            with open(path,'rb') as stream:
                stream.readline();stream.readline();stream.readline()
                pixel=struct.unpack('<3f',stream.read())
        self.assertEqual(pixel,(0,0,1))

    def test_per_light_override_wins_shader_exclusion(self):
        links={'materials':{'m':{'mode':'exclude','members':['sun']}},'lights':{'sun':{'mode':'include','members':['mesh']}}}
        self.assertEqual(native_light_links.allowed(links,'mesh|part','m',{'sun'}),['sun'])
        self.assertEqual(native_light_links.allowed(links,'other','m',{'sun'}),[])

if __name__=='__main__':unittest.main()
