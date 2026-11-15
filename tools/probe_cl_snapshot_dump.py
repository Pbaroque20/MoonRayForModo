# python
"""Command line: PROBE_SCENE read as a render reads it (host.snapshot) and as realtime does, each written as JSON to
PROBE_OUT/render.json and realtime.json with the time each reading took, for comparing a reading before and after a
change to the plugin (tools/compare_snapshot_dumps.py). Fields starting with _ are left out."""
import json
import os
import pathlib
import time
import traceback
import lx

out = pathlib.Path(os.environ['PROBE_OUT'])
out.mkdir(parents=True, exist_ok=True)


def plain(value):
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items() if not str(k).startswith('_')}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return [plain(v) for v in value]
    except TypeError:
        return repr(value)


report = {}
try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import host
    for mode, evaluated in (('render', False), ('realtime', True)):
        host.snapshot(evaluated_geometry=evaluated)
        times = []
        for _ in range(3):
            start = time.perf_counter()
            scene = host.snapshot(evaluated_geometry=evaluated)
            times.append(round(time.perf_counter() - start, 3))
        report[mode] = times
        (out / (mode + '.json')).write_text(json.dumps(plain(scene), sort_keys=True, default=str))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'times.json').write_text(json.dumps(report, indent=1))
lx.eval('!app.quit')
