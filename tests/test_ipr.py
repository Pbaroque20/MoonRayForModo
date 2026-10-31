"""Deferred IPR request checks; run explicitly outside Modo."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo.ipr import WIDGET_SAMPLES,prepare,widget_samples

class IprTests(unittest.TestCase):
    def test_preview_copy_preserves_final_settings(self):
        scene={'width':1920,'height':1080,'render_settings':{'sampling_mode':2,'min_adaptive_samples':16,'max_adaptive_samples':256},'denoising':{'engine':'optix'}}
        original=copy.deepcopy(scene)
        preview,w,h=prepare(scene,640,360,4)
        self.assertEqual(scene,original)
        self.assertEqual((w,h),(160,90))
        self.assertEqual(preview['render_settings']['max_adaptive_samples'],1)
        self.assertEqual(preview['render_settings']['min_adaptive_samples'],1)
        self.assertEqual(preview['render_settings']['sampling_mode'],0)
        self.assertEqual(preview['render_settings']['target_adaptive_error'],100)
        self.assertIsNot(preview['render_settings'],scene['render_settings'])
        self.assertEqual(preview['denoising'],scene['denoising'])

    def test_widget_samples_reach_the_scene_and_standard_is_as_it_was(self):
        self.assertEqual(widget_samples('standard'),(64,5.0))
        self.assertEqual(widget_samples('standard',True),(4,50.0))
        self.assertEqual(widget_samples('gone'),(64,5.0))
        for key,_,*_ in WIDGET_SAMPLES:
            for live in (False,True):
                samples,error=widget_samples(key,live)
                # As the widget asks: its own cap and noise put in first, or the scene's would hold them back.
                settings={'sampling_mode':2,'min_adaptive_samples':2,'max_adaptive_samples':samples,'target_adaptive_error':error}
                preview,_w,_h=prepare({'width':384,'height':384,'render_settings':settings},384,384,1,640,samples,error)
                self.assertEqual(preview['render_settings']['max_adaptive_samples'],samples)
                self.assertEqual(preview['render_settings']['target_adaptive_error'],error)

    def test_uniform_gives_every_pixel_the_square_grid_within_the_cap(self):
        scene={'width':640,'height':360,'render_settings':{'sampling_mode':2,'min_adaptive_samples':16,'max_adaptive_samples':1024}}
        for cap,grid in ((32,5),(64,8),(128,11)):
            preview,_,_=prepare(scene,640,360,4,640,cap,100.0,'uniform')
            self.assertEqual(preview['render_settings']['sampling_mode'],0)
            self.assertEqual(preview['_uniform_grid'],grid)
        adaptive,_,_=prepare(scene,640,360,4,640,64,100.0)
        self.assertEqual((adaptive['render_settings']['sampling_mode'],adaptive['render_settings']['max_adaptive_samples']),(2,64))
        self.assertNotIn('_uniform_grid',adaptive)
        # Never more than the scene's own render settings give.
        few,_,_=prepare(dict(scene,render_settings={'sampling_mode':2,'max_adaptive_samples':36}),640,360,4,640,128,100.0,'uniform')
        self.assertEqual(few['_uniform_grid'],6)
        with self.assertRaises(ValueError):prepare(scene,640,360,4,640,64,100.0,'random')

    def test_ipr_bypasses_denoiser_and_guides(self):
        from moonray_modo import denoising
        scene={'width':640,'denoising':{'engine':'optix','preview':True,'final':True},
               '_denoise_guides':{'albedo':'old.exr'},'preview_buffer':'denoised_beauty'}
        preview,_,_=prepare(scene,640,360,4)
        self.assertFalse(denoising.enabled(preview))
        self.assertFalse(denoising.guides_required(preview))
        self.assertNotIn('_denoise_guides',preview)
        self.assertEqual(preview['preview_buffer'],'beauty')
        self.assertIn('_denoise_guides',scene)
        self.assertTrue(denoising.enabled(preview,final=True))
        regular=dict(scene,preview_buffer='beauty')
        self.assertTrue(denoising.enabled(regular))
        self.assertTrue(denoising.guides_required({'denoising':{'engine':'off'}}))

    def test_idle_refinement_preserves_quick_pass(self):
        from moonray_modo.ipr import refine
        scene={'width':640}
        quick,_,_=prepare(scene,640,360,4)
        refined=refine(quick)
        self.assertEqual(quick['render_settings']['max_adaptive_samples'],1)
        self.assertEqual(refined['render_settings']['max_adaptive_samples'],16)
        self.assertEqual(refined['render_settings']['sampling_mode'],0)
        self.assertTrue(refined['_ipr_refined'])
        self.assertTrue(refined['_ipr'])

    def test_never_raises_existing_cap_or_resolution(self):
        scene={'width':128,'height':256,'render_settings':{'sampling_mode':0}}
        for cap in (32,64):
            many,_,_=prepare(dict(scene,render_settings=dict(scene.get('render_settings',{}),sampling_mode=2,max_adaptive_samples=256)),640,360,4,160,cap)
            self.assertEqual(many['render_settings']['max_adaptive_samples'],cap)
        with self.assertRaises(ValueError):prepare(scene,640,360,4,160,48)
        # The width may be any of the realtime preview's sizes, and is never wider than the preview or the scene.
        wide=dict(scene,width=1920,height=1080)
        self.assertEqual(prepare(wide,640,360,4,640)[1:],(640,360))
        self.assertEqual(prepare(wide,640,360,4,1280)[1:],(640,360))
        self.assertEqual(prepare(wide,1280,720,4,960)[1:],(960,540))
        with self.assertRaises(ValueError):prepare(wide,640,360,4,500)
        preview,w,h=prepare(scene,320,640,1)
        self.assertEqual((w,h),(128,256))
        self.assertEqual(preview['render_settings']['max_adaptive_samples'],1)

    def test_looser_existing_error_is_preserved(self):
        scene={'width':640,'height':360,'render_settings':{'target_adaptive_error':200}}
        preview,_,_=prepare(scene,640,360,4)
        self.assertEqual(preview['render_settings']['target_adaptive_error'],200)

if __name__=='__main__':unittest.main()
