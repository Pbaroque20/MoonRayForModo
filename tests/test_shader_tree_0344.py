"""Deferred mask continuation checks. Run explicitly; never run by installation."""
import sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import graph,material_groups,moonshine

class MaskContinuation(unittest.TestCase):
    def test_second_partition_uses_previous_mask(self):
        first=[]
        maps=graph.bindings({'layers':[{'kind':'constant','effect':'groupMask','value':[.25]*3}]},1,first)
        seed=maps['layerMask'].rsplit(', ',1)[0]+')'
        second=[]
        graph.bindings({'layers':[{'kind':'constant','effect':'groupMask','value':[.5]*3,'blend':'multiply'}]},2,second,group_mask=seed)
        self.assertIn(seed[:-1]+', Rgb(1, 1, 1))','\n'.join(second))

    def test_target_mask_survives_material_boundary(self):
        state={};lines=[]
        graph.bindings({'layers':[{'identity':'mask','kind':'constant','effect':'layerMask','mask_target':'later','value':[.5]*3}]},1,lines,separate_masks=True,mask_state=state)
        self.assertIn('later',state)
        result=graph.bindings({'base_layer_id':'later','layers':[]},2,lines,separate_masks=True,mask_state=state)
        self.assertIn('_rowMask',result)
        self.assertNotIn('later',state)

    def test_group_target_precedes_material_in_flattened_stack(self):
        group={'id':'g','opacity':1,'blend':'normal'}
        mask={'identity':'mask','kind':'constant','effect':'layerMask','mask_target':'g','value':[.5]*3,'absolute_groups':[]}
        layers=material_groups.flatten([{'base_layer_id':'m','material_groups':[group],'layers':[mask]}])
        self.assertEqual([v['identity'] for v in layers],['mask','m'])
        self.assertEqual(layers[0]['groups'],[])

    def test_native_group_target_applies_once(self):
        group={'id':'g','opacity':1,'blend':'normal'}
        mask={'kind':'constant','effect':'layerMask','mask_target':'g','value':[.5]*3}
        stack=[{'color':[0,0,1]}, {'color':[1,0,0],'native_shader':'DwaBaseMaterial','material_groups':[group],'layers':[mask]},
               {'color':[0,1,0],'native_shader':'DwaBaseMaterial','material_groups':[group]}]
        lines=[]
        with patch('moonray_modo.shader_library.emit',return_value='DwaBaseMaterial("native")'),patch('moonray_modo.shader_library.compatible',return_value=True):
            moonshine.emit_stack(stack,'test',0,lines)
        mixes=[s for s in lines if s.startswith('DwaLayerMaterial(')]
        self.assertEqual(len(mixes),1)
        self.assertIn('["mask"] = bind(ModoTextureMap(',mixes[0])

if __name__=='__main__':unittest.main()
