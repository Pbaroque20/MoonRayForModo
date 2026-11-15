# python
"""Command line: a scene (PROBE_SCENE) read as MoonLightIPR reads it (host.snapshot under host.by_engine('moonlightipr'))
at its current time, pickled to PROBE_OUT (test-results/snapshot.pickle), for rendering it again outside Modo with
tools/check_moonlightipr_session.py's Session. Notes in PROBE_OUT + '.json'."""
import json
import os
import pathlib
import pickle
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\snapshot.pickle'))
out.parent.mkdir(parents=True, exist_ok=True)
report = {}
try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import host
    with host.by_engine('moonlightipr'):
        snap = host.snapshot()
    snap.setdefault('time', float(lx.eval('select.time ?')))
    out.write_bytes(pickle.dumps(snap, protocol=4))
    report['meshes'] = len(snap.get('meshes') or [])
    report['time'] = snap.get('time')
except Exception:
    report['error'] = traceback.format_exc()
pathlib.Path(str(out) + '.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
