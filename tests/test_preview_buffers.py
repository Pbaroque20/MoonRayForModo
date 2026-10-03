"""Deferred serializer coverage: run explicitly; no Modo or renderer launch."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo import rdla, options

class PreviewBuffersTests(unittest.TestCase):
    def scene(self):
        return {'camera':{'matrix':rdla.IDENTITY,'focal_mm':50,'film_mm':36},'meshes':[],
                'preview_buffer_files':{key:key+'.exr' for key in ('beauty',*options.AOVS)}}

    def test_all_buffers_have_separate_outputs(self):
        text=rdla.scene_text(self.scene())
        self.assertEqual(text.count('RenderOutput('),1+len(options.AOVS))
        for key in ('beauty',*options.AOVS):
            self.assertIn('RenderOutput("/modo/preview/'+key+'")',text)
            self.assertIn('["file_name"] = "'+key+'.exr"',text)

    def test_final_aov_selection_is_independent(self):
        scene=self.scene();scene['aovs']=['depth']
        text=rdla.scene_text(scene,output_file='final.exr')
        self.assertNotIn('/modo/preview/',text)
        self.assertEqual(text.count('RenderOutput('),2)
        self.assertIn('RenderOutput("/modo/aov/depth")',text)

    def test_legacy_single_buffer(self):
        scene=self.scene();scene.pop('preview_buffer_files')
        scene.update(preview_buffer='normal',preview_buffer_file='legacy.exr')
        text=rdla.scene_text(scene)
        self.assertEqual(text.count('RenderOutput('),1)
        self.assertIn('["file_name"] = "legacy.exr"',text)

    def test_invalid_buffer_rejected(self):
        scene=self.scene();scene['preview_buffer_files']={'invalid':'bad.exr'}
        with self.assertRaisesRegex(ValueError,'Unknown preview buffer'):rdla.scene_text(scene)

if __name__=='__main__':unittest.main()
