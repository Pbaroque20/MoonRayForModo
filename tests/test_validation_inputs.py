"""Deferred release-fingerprint checks; creates only temporary fixture files."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from validation_inputs import fingerprint,require_feature_reports


class ValidationInputs(unittest.TestCase):
    def test_stale_shader_or_source_invalidates_previous_reports(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);runtime=root/'runtime';runtime.mkdir()
            for name in ('moonray.exe','ModoTextureMap.so'):
                (runtime/name).write_bytes(b'fixture')
            for name in ('tools/validation_inputs.py','tools/validate_cpu_feature_renders.py',
                         'native-modo/geometry_bridge.cpp','native-modo/render_cache.cpp',
                         'kit/MoonRayForModo/export.py'):
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture',encoding='utf-8')
            inputs=fingerprint(root,runtime)
            for feature in ('materials','textures','geometry','environments','rendering'):
                path=root/'test-results/cpu-features'/feature/'render-report.json'
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps({'passed':True,'inputs':inputs}),encoding='utf-8')
            self.assertEqual(require_feature_reports(root,runtime),inputs)
            shader=runtime/'ModoTextureMap.so'
            shader.write_bytes(b'changed')
            with self.assertRaises(ValueError): require_feature_reports(root,runtime)
            shader.write_bytes(b'fixture')
            (root/'kit/MoonRayForModo/export.py').write_text('changed',encoding='utf-8')
            with self.assertRaises(ValueError): require_feature_reports(root,runtime)


if __name__=='__main__': unittest.main()
