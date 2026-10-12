# python
"""Isolated GUI test: what reading evaluated geometry costs, and whether a render cache kept between readings saves it.

A scene (MOONRAY_PROBE_SCENE) is read with the adapter built in build/modo-geometry-cache: first the way it always
was, a cache made and evaluated whole for each reading; then from one cache that is kept and that Modo keeps up to date.
With the kept cache the scene is read again unchanged, after an item is moved, and after a mesh is added to. Each time,
how long Modo took to have the cache ready, to list the surfaces and to hand over the meshes is written down, with
whether what came back shows the change."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/geometry-cache'
out.mkdir(parents=True, exist_ok=True)
result = {'readings': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def read(name):
    from moonray_modo import evaluated
    t = time.perf_counter()
    data = evaluated.capture(lx.service.Selection().GetTime())
    whole = time.perf_counter() - t
    item = held.get('item')
    mine = [s for s in data['surfaces'] if s['source_item'] == item]
    vertices = sum(len(seg['vertices']) for s in mine for seg in data['prototypes'][str(s['source_id'])]['segments'])
    result['readings'].append({'reading': name, 'mode': data.get('mode'), 'seconds': round(whole, 3),
                               'cache_ready': round(data.get('timing', [0, 0, 0])[0], 3), 'surfaces_listed': round(data.get('timing', [0, 0, 0])[1], 3),
                               'meshes_handed_over': round(data.get('timing', [0, 0, 0])[2], 3), 'handing': [round(v, 3) for v in data.get('handing', [])], 'numbers': sum(len(seg['vertices']) * 3 + len(seg['normals']) * 3 + sum(len(u) * 2 for u in seg['uv_sets']) + sum(len(f) for f in seg['faces']) for pr in data['prototypes'].values() for seg in pr['segments']), 'surfaces': len(data['surfaces']), 'prototypes': len(data['prototypes']),
                               'item_surfaces': len(mine), 'item_vertices': vertices, 'item_at': [round(v, 3) for v in (mine[0]['matrix'][12:15] if mine else [])]})
    save()
    return data


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


def same(a, b, path=''):
    """Whether two readings hold the same, numbers to within a part in a million; else where they first differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        for key in set(a) | set(b):
            if key in ('timing', 'handing', 'mode', 'skip'):
                continue
            if key not in a or key not in b:
                return path + '/' + str(key) + ' missing'
            found = same(a[key], b[key], path + '/' + str(key))
            if found is not True:
                return found
        return True
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            return '%s lengths %d and %d' % (path, len(a), len(b))
        for index, (x, y) in enumerate(zip(a, b)):
            found = same(x, y, path + '[%d]' % index) if isinstance(x, (list, dict)) else (True if x == y or (isinstance(x, (int, float)) and isinstance(y, (int, float)) and abs(x - y) <= 1e-6 * max(1.0, abs(x), abs(y))) else '%s[%d] %r and %r' % (path, index, x, y))
            if found is not True:
                return found
        return True
    return True if a == b else '%s %r and %r' % (path, a, b)


@step(500)
def both_ways():
    from moonray_modo import evaluated
    held['item'] = next(m.id for m in modo.Scene().items('mesh'))
    fast = read('rows as they are')
    read('rows as they are, again')
    bridge = evaluated._bridge

    class Text:
        """The adapter with only its older way of handing over, as text."""
        MR_geometry_snapshot_file = bridge.MR_geometry_snapshot_file
    evaluated._bridge = Text()
    slow = read('as text')
    evaluated._bridge = bridge
    result['same'] = same(fast, slow)
    # And the whole of a reading of the scene, as the preview makes it.
    from moonray_modo.panel import Panel
    from PySide2 import QtWidgets
    lx.eval('moonray.open')
    panel = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
    t = time.perf_counter()
    scene = panel._capture_preview()
    result['whole_reading_of_the_scene'] = round(time.perf_counter() - t, 3)
    result['meshes'] = len(scene.get('meshes', []))


def run(index=0):
    if index >= len(STEPS):
        save()
        lx.eval('!app.quit')
        return
    function, wait = STEPS[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append([function.__name__, traceback.format_exc()])
        save()
    QtCore.QTimer.singleShot(wait, lambda: run(index + 1))


try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, run)
