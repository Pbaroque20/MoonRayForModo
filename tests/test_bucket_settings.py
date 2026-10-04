"""Bucket controls are plugin launch settings, not native SceneVariables."""
import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"kit/MoonRayForModo/python"))
from moonray_modo import options,rdla
from test_compatibility_035 import scene

class BucketSettings(unittest.TestCase):
    def test_auto_default_and_manual_choices(self):
        self.assertEqual(options.render_values({})['bucket_size'],0)
        for size in (0,32,64,128,256):
            self.assertEqual(options.render_values({'bucket_size':size})['bucket_size'],size)
        for size in (-1,16,100,512):
            with self.assertRaises(ValueError):options.render_values({'bucket_size':size})
    def test_bucket_option_is_not_exported_as_unknown_scene_attribute(self):
        value=scene();value['render_settings']={'bucket_size':64,'batch_tile_order':6}
        text=rdla.scene_text(value)
        self.assertNotIn('["bucket_size"]',text)
        self.assertIn('["progressive_tile_order"] = 6',text)

    def test_changing_manual_size_restarts_persistent_process(self):
        from types import SimpleNamespace
        from moonray_modo.persistent import Session
        calls=[]
        state=SimpleNamespace(running=lambda:True,signature=('runtime',0,'auto',0),
            stopping=False,sent=None,process=SimpleNamespace(kill=lambda:calls.append('restart')),
            _dispatch=lambda:calls.append('dispatch'))
        Session.submit(state,'scene','runtime',0,'auto',1,0)
        self.assertEqual(calls,['dispatch'])
        Session.submit(state,'scene','runtime',0,'auto',2,64)
        self.assertEqual(calls,['dispatch','restart'])
        self.assertEqual(state.latest['bucket_size'],64)
