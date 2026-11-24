# python
"""Command line: a scene (PROBE_SCENE) with its render camera set to Spherical Map, read as a MoonRay render reads it, and
the scene MoonRay is given written to PROBE_RDLA, with notes (the camera rendered through, notices) in PROBE_RDLA + '.json'."""
import json
import os
import pathlib
import traceback
import lx

target = pathlib.Path(os.environ['PROBE_RDLA'])
report = {}
try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    import modo
    camera = modo.Scene().renderCamera
    camera.channel('projType').set(os.environ.get('PROBE_PROJECTION', 'spherical'))
    from moonray_modo import host, rdla
    snap = host.snapshot()
    report['cameras'] = [{k: e.get(k) for k in ('class', 'name', 'parameters')} for e in snap.get('entities') or []
                         if e.get('class', '').endswith('Camera')]
    report['warnings'] = list(snap.get('warnings') or [])
    target.write_text(rdla.scene_text(snap, output_file=str(target.with_suffix('.exr'))), encoding='utf-8')
except Exception:
    report['error'] = traceback.format_exc()
pathlib.Path(str(target) + '.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
