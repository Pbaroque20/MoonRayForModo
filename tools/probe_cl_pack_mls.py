# python
"""Command line: open scenes and pack each as MoonLightIPR is given it (<name>.mls beside it), for
tools/render_snapshot_moonlightipr.py. MOONRAY_PROBE_SCENES: scene files separated by ;. MOONRAY_PROBE_SIZE: width,height
(default 640,180). Writes pack-report.json beside the first scene."""
import json
import os
import pathlib
import traceback
import lx

scenes = [pathlib.Path(p) for p in os.environ['MOONRAY_PROBE_SCENES'].split(';') if p]
width, height = (int(v) for v in os.environ.get('MOONRAY_PROBE_SIZE', '640,180').split(','))
report = {}
for scene in scenes:
    entry = report[str(scene)] = {}
    try:
        lx.eval('scene.open {%s} normal' % scene)
        from moonray_modo import host, moonlightipr_scene
        with host.by_engine('moonlightipr'):
            seen = host.snapshot()
        payload, _, entry['warnings'] = moonlightipr_scene.pack(seen, width, height, 0.0, set(), 512, denoise=False)
        (scene.parent / (scene.stem + '.mls')).write_bytes(payload)
        entry['bytes'] = len(payload)
        lx.eval('!scene.close')
    except Exception:
        entry['error'] = traceback.format_exc()[-2500:]
(scenes[0].parent / 'pack-report.json').write_text(json.dumps(report, indent=1, default=str))
