# python
"""Headless Modo probe (tools/launch_cl_probe.py): MOONRAY_PROBE_LXO opened and exported as Export as MoonRay Scene
writes it (RDLA with its outputs) into MOONRAY_PROBE_OUT, with the export's notices and timings in report.json there."""
import json
import os
import pathlib
import time
import traceback
import lx

source = pathlib.Path(os.environ['MOONRAY_PROBE_LXO'])
out = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
out.mkdir(parents=True, exist_ok=True)
result = {'scene': str(source)}
try:
    started = time.perf_counter()
    lx.eval('scene.open {%s} normal' % source)
    result['opened_seconds'] = round(time.perf_counter() - started, 1)
    from moonray_modo import scene_export
    warnings = []
    started = time.perf_counter()
    written = scene_export.export({'path': out / (source.stem + '.rdla'), 'format': 'rdla', 'outputs': True, 'collect': False,
                                   'frames': False}, warnings)
    result['export_seconds'] = round(time.perf_counter() - started, 1)
    result['written'] = [str(p) for p in written]
    result['warnings'] = warnings
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
