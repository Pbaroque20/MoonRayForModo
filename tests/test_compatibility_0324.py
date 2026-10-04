"""Deferred preview integration checks; no tests execute during installation."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import outputs,rdla,options

class Preview0324(unittest.TestCase):
    def scene(self):
        return {'camera':{'matrix':rdla.IDENTITY,'film_mm':36,'focal_mm':50},
            'meshes':[],'lights':[],'materials':{},'custom_aovs':[{'name':'ObjectMask','kind':'cryptomatte'}],
            'preview_buffer_files':{'beauty':'beauty.exr','ObjectMask':'mask.exr'}}
    def test_crypto_is_available_and_not_color_managed(self):
        scene=self.scene();self.assertEqual(outputs.preview(scene)['ObjectMask']['result'],13)
        self.assertEqual(outputs.display_kind(scene,'ObjectMask'),'cryptomatte')
    def test_preview_collects_id_buffer(self):
        text=rdla.scene_text(self.scene(),32,32,1,0)
        self.assertIn('["deep_id_attribute_names"] = {"modo_object_id"}',text)
        self.assertIn('["cryptomatte_support_resume_render"] = true',text)
    def test_environment_outputs_and_labels(self):
        scene=self.scene();scene['preview_buffer_files'].update({key:key+'.exr' for key in ('environment_background','environment_lighting')})
        text=rdla.scene_text(scene,32,32,1,.15)
        self.assertIn('["label"] = "modo_environment"',text)
        for name in ('environment_background','environment_lighting'):
            self.assertIn(options.AOVS[name][1]['lpe'],text)

if __name__=='__main__':unittest.main()
