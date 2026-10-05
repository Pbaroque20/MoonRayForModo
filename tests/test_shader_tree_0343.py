"""Deferred Shader Tree regression checks; not run by the installer."""
import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import gradients,graph,group_scale,material_groups,moonshine,textures

class Item:
    def __init__(self,kind='mask',parent=None,**channels):
        self.type=kind;self.parent=parent;self.channels=channels

def channel(item,name,default=None):return item.channels.get(name,default)

class ShaderTree0343(unittest.TestCase):
    def test_nested_scale_and_opt_out(self):
        outer=Item(scaleGroup=2,scaleUV=True,scaleSize=True,scaleBump=True,scaleSDist=True)
        inner=Item(parent=outer,scaleGroup=3,scaleUV=True,scaleBump=True,scaleSDist=True)
        layer=Item('imageMap',inner)
        self.assertEqual(group_scale.factor(layer,'scaleUV',channel),6)
        self.assertEqual(group_scale.texture(layer,{'scale':[12,6]},channel)['scale'],[2,1])
        layer.channels['ignSclGrp']=True
        self.assertEqual(group_scale.factor(layer,'scaleUV',channel),1)
    def test_invalid_scale_rejected(self):
        for value in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):group_scale.factor(Item(parent=Item(scaleUV=True,scaleGroup=value)),'scaleUV',channel)
    def test_read_evaluated_gradient(self):
        class Filter:
            def __init__(self,value):pass
            def test(self):return True
            def Generate(self,x):return x*x
        layer=SimpleNamespace(channel=lambda name:SimpleNamespace(get=lambda:object()))
        with patch.dict(sys.modules,{'lx':SimpleNamespace(object=SimpleNamespace(GradientFilter=Filter))}):
            data=gradients.capture(layer,lambda item,name,default:'driverA',False)
        self.assertEqual(len(data['colors']),257)
        self.assertEqual(data['colors'][128],[.25]*3)
        self.assertEqual(gradients.sample(data,2),[1]*3)
    def test_driver_not_a_material_parameter(self):
        lines=[]
        data={'input':'driverA','positions':[0,1],'colors':[[0,0,0],[1,0,0]]}
        maps=graph.bindings({'layers':[{'kind':'constant','effect':'driverA','value':[.5]*3},
                                     {'kind':'gradient','effect':'diffCol','gradient':data}]},0,lines)
        self.assertNotIn('driverA',maps);self.assertIn('diffuseColor',maps)
        ramp='\n'.join(lines).split('RampMap(',1)[1]
        self.assertIn('["input"] = bind(ModoTextureMap(',ramp)
        self.assertIn(', 1)',ramp)
    def test_layer_mask_precedes_its_material_row(self):
        mask={'kind':'constant','effect':'layerMask','mask_target':'upper','identity':'mask','value':[0]*3}
        stack=[{'base_layer_id':'lower','color':[0,0,1]},
               {'base_layer_id':'upper','color':[1,0,0],'layers':[mask]}]
        layers=material_groups.flatten(stack)
        ids=[layer.get('identity') for layer in layers]
        self.assertLess(ids.index('mask'),ids.index('upper'))
        lines=[];graph.bindings(material_groups.merged(stack),0,lines)
        self.assertIn('["mask"]','\n'.join(lines))
    def test_native_material_target_mask_is_not_dropped(self):
        lines=[];maps=graph.bindings({'base_layer_id':'native','layers':[
            {'kind':'constant','effect':'layerMask','mask_target':'native','value':[.5]*3}]},0,lines)
        self.assertIn('layerMask',maps)
        self.assertNotIn('singleLayerMask',maps)
    def test_native_group_opacity_composites_once(self):
        group={'id':'g','opacity':.5,'blend':'normal'}
        stack=[{'color':[0,0,1]},
               {'color':[1,0,0],'native_shader':'DwaBaseMaterial','material_groups':[group]},
               {'color':[0,1,0],'native_shader':'DwaBaseMaterial','material_groups':[group]}]
        lines=[]
        with patch('moonray_modo.shader_library.emit',return_value='DwaBaseMaterial("native")'),patch('moonray_modo.shader_library.compatible',return_value=True):
            moonshine.emit_stack(stack,'test',0,lines)
        mixes=[line for line in lines if line.startswith('DwaLayerMaterial(')]
        self.assertEqual(len(mixes),1)
        self.assertIn('["mask"] = 0.5',mixes[0])

    def test_masked_native_stack_keeps_lower_surface(self):
        stack=[{'color':[0,0,1],'shader':'DwaBaseMaterial'},
               {'color':[1,0,0],'native_shader':'DwaBaseMaterial','native_parameters':{},'base_layer_id':'native',
                'layers':[{'kind':'constant','effect':'layerMask','mask_target':'native','value':[.5]*3}]}]
        lines=[]
        with patch('moonray_modo.shader_library.emit',return_value='DwaBaseMaterial("native")'),patch('moonray_modo.shader_library.compatible',return_value=True):
            moonshine.emit_stack(stack,'test',0,lines)
        self.assertIn('DwaLayerMaterial(','\n'.join(lines))
        self.assertIn('["mask"] = bind(','\n'.join(lines))

if __name__=='__main__':unittest.main()
