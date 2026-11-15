# python
"""Command line: the scene read (host.snapshot) with each channel read once (host.held_channels) against the same read
without it, for PROBE_SCENE: whether the two give the same scene, field by field, and how long each takes, as a render
reads the scene and as realtime does. Writes PROBE_OUT/report.json (test-results/channel-store)."""
import json
import os
import pathlib
import time
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\channel-store'))
out.mkdir(parents=True, exist_ok=True)
result = {'scene': os.environ.get('PROBE_SCENE')}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def plain(value):
    """The scene as JSON-like data: the lists the adapter hands over (rows.Rows, rows.Faces) as plain lists."""
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    try:
        return [plain(v) for v in value]
    except TypeError:
        return repr(value)


def differences(a, b, path='', found=None):
    found = [] if found is None else found
    if len(found) >= 20:
        return found
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key.startswith('_'):
                continue
            if key not in a or key not in b:
                found.append(path + '/' + key + ' only in ' + ('new' if key in b else 'old'))
            else:
                differences(a[key], b[key], path + '/' + key, found)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            found.append('%s: %d items, was %d' % (path, len(b), len(a)))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                differences(x, y, '%s[%d]' % (path, i), found)
    elif a != b and not (isinstance(a, float) and isinstance(b, float) and abs(a - b) <= 1e-9 * max(1.0, abs(a))):
        found.append('%s: %r, was %r' % (path, b, a)[:300])
    return found


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import host
    from moonray_modo.layers import held_tree

    def without(evaluated):
        with held_tree():
            return host._snapshot(evaluated)

    for mode, evaluated in (('render', False), ('realtime', True)):
        try:
            host.snapshot(evaluated_geometry=evaluated)  # Modo's caches warmed
            times = {'old': [], 'new': []}
            for _ in range(2):
                start = time.perf_counter()
                old = without(evaluated)
                times['old'].append(round(time.perf_counter() - start, 3))
                start = time.perf_counter()
                new = host.snapshot(evaluated_geometry=evaluated)
                times['new'].append(round(time.perf_counter() - start, 3))
            found = differences(plain(old), plain(new))
            result[mode] = {'seconds': times, 'same': not found, 'differences': found}
        except Exception:
            result[mode + '_error'] = traceback.format_exc()
        save()
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
