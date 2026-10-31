# python
"""Reads a scene (MOONRAY_PROBE_SCENE) as the plugin does, for rendering outside Modo. Run through tools/launch_cl_probe.py. Writes
MOONRAY_PROBE_OUT/snapshot.pickle and report.json."""
import json
import os
import pathlib
import pickle
import traceback
import lx

out = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    from moonray_modo import host
    lx.eval('!scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    snapshot = host.snapshot()
    report['warnings'] = snapshot.get('warnings')
    report['meshes'] = [(m.get('name'), len(m.get('faces') or []), m.get('material')) for m in snapshot.get('meshes', [])]
    report['lights'] = [(l.get('name'), l.get('type') or l.get('kind')) for l in snapshot.get('lights', [])]
    report['size'] = (snapshot.get('width'), snapshot.get('height'))
    (out / 'snapshot.pickle').write_bytes(pickle.dumps(snapshot, protocol=4))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
