"""Deferred IPR request checks; run explicitly outside Modo."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'kit/MoonRayForModo/python'))
from moonray_modo.ipr import prepare

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

    def test_never_raises_existing_cap_or_resolution(self):
        scene={'width':128,'height':256,'render_settings':{'sampling_mode':0}}
        preview,w,h=prepare(scene,320,640,1)
        self.assertEqual((w,h),(128,256))
        self.assertEqual(preview['render_settings']['max_adaptive_samples'],1)

    def test_looser_existing_error_is_preserved(self):
        scene={'width':640,'height':360,'render_settings':{'target_adaptive_error':200}}
        preview,_,_=prepare(scene,640,360,4)
        self.assertEqual(preview['render_settings']['target_adaptive_error'],200)

if __name__=='__main__':unittest.main()
