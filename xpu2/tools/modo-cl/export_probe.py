# python
"""Headless Modo probe: each scene in MOONRAY_PROBE_SCENES (separated by ';') opened and exported as the private XPU2
kit's Export as MoonRay Scene writes it (RDLA with its outputs) into MOONRAY_PROBE_OUT/<scene name>/, with the
export's notices and timings in report.json there."""
import json
import os
import pathlib
import time
import traceback
import lx

out_root = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
for source in [pathlib.Path(s) for s in os.environ['MOONRAY_PROBE_SCENES'].split(';') if s]:
    out = out_root / source.stem
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
    try:
        lx.eval('scene.close')
    except Exception:
        pass
