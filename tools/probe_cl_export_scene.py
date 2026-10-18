# python
"""Command-line test: a scene (MOONRAY_PROBE_SCENE) exported as the plugin's Export as MoonRay Scene writes it, as RDLA,
into test-results/cl-export/<scene name>.rdla, for MoonRay to be run on it outside Modo. Also noted: the scene's
materials by kind, and the export's notices. With MOONRAY_PROBE_PLACEHOLDER set to a picture, a texture the scene names
that is not on this machine is read as that picture instead (each listed), for a scene sent from another machine
without its textures."""
import json
import os
import pathlib
import time
import traceback
import lx

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export')
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    source = pathlib.Path(os.environ['MOONRAY_PROBE_SCENE'])
    started = time.perf_counter()
    lx.eval('scene.open {%s} normal' % source)
    result['opened_seconds'] = round(time.perf_counter() - started, 1)
    from moonray_modo import scene_export, textures
    stand_in = os.environ.get('MOONRAY_PROBE_PLACEHOLDER')
    if stand_in:
        result['stood_in'] = []
        original = textures.prepare

        def prepare(source, *args, **kwargs):
            if '<UDIM>' not in str(source) and not pathlib.Path(source).is_file():
                result['stood_in'].append(str(source))
                source = stand_in
            return original(source, *args, **kwargs)
        textures.prepare = prepare
    warnings = []
    started = time.perf_counter()
    written = scene_export.export({'path': out / (source.stem + '.rdla'), 'format': 'rdla', 'outputs': True, 'collect': False, 'frames': False}, warnings)
    result['export_seconds'] = round(time.perf_counter() - started, 1)
    result['written'] = [str(p) for p in written]
    result['warnings'] = warnings
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
