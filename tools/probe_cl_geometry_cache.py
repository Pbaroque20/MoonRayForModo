# python
"""Command line: the geometry cache across Modo's sessions (geometry_cache). One run of three, by MOONRAY_PROBE_MODE,
each in a Modo of its own, on MOONRAY_PROBE_SCENE, with a cache folder of the probe's own
(test-results/geometry-cache/<label>/cache):
- first: the folder emptied, a whole reading, kept.
- edit: one mesh moved 1 mm (unsaved), a reading by way of the kept one, then a whole reading from Modo
  (kept=False) to compare every mesh with.
- same: nothing changed, a reading by way of the kept one.
- shape: one point of the largest mesh moved 1 cm, then as edit.
Writes <mode>.json: the time, what geometry_cache.LAST says, and for edit whether the meshes match."""
import hashlib
import json
import os
import pathlib
import pickle
import shutil
import threading
import time
import traceback
import lx
import modo

label = os.environ.get('MOONRAY_PROBE_LABEL', 'scene')
mode = os.environ.get('MOONRAY_PROBE_MODE', 'first')
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\geometry-cache') / label
cache = out / 'cache'
out.mkdir(parents=True, exist_ok=True)
result = {'mode': mode}


def save():
    (out / (mode + '.json')).write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')


def settle():
    for thread in threading.enumerate():
        if thread is not threading.current_thread() and thread.daemon:
            thread.join(600)


def meshes(shot):
    found = {}
    for mesh in shot.get('meshes') or []:
        held = {k: v for k, v in mesh.items() if k not in ('name',)}
        found[str(mesh.get('identity')) + '|' + str(mesh.get('material')) + '|' + str(mesh.get('name'))] = \
            hashlib.blake2b(pickle.dumps(held, protocol=4), digest_size=16).hexdigest()
    return found


try:
    if mode == 'first' and cache.exists():
        shutil.rmtree(cache)
    from moonray_modo import cache_folder, host, evaluated, geometry_cache
    cache_folder._HELD['root'] = cache
    cache_folder._HELD['scene'] = True
    began = time.perf_counter()
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    result['open_seconds'] = round(time.perf_counter() - began, 3)
    scene = modo.Scene()
    if mode in ('edit', 'shape'):
        # The mesh with the most polygons, which renders.
        target = max(scene.items('mesh', superType=False), key=lambda m: m.geometry.numPolygons)
        if mode == 'edit':
            target.position.x.set(target.position.x.get() + 0.001)
        else:
            point = target.geometry.vertices[0]
            x, y, z = point.position
            point.position = (x + 0.01, y, z)
            target.geometry.setMeshEdits()
        result['edited'] = target.name
        result['changed_after_edit'] = int(lx.eval1('query sceneservice scene.changed ? current'))
    began = time.perf_counter()
    shot = host.snapshot(evaluated_geometry=True)
    result['reading_seconds'] = round(time.perf_counter() - began, 3)
    result['cache'] = dict(geometry_cache.LAST)
    result['meshes'] = len(shot.get('meshes') or [])
    result['adapter_timing'] = (shot.get('_evaluated_data') or {}).get('timing')
    result['adapter_handing'] = (shot.get('_evaluated_data') or {}).get('handing')
    began = time.perf_counter()
    settle()
    result['kept_written_seconds'] = round(time.perf_counter() - began, 3)
    save()
    if mode in ('edit', 'same', 'shape'):
        fast = meshes(shot)
        del shot
        real = evaluated.capture
        evaluated.capture = lambda *a, **k: real(*a, **dict(k, kept=False)) if k.get('only') is None else real(*a, **k)
        try:
            began = time.perf_counter()
            whole = host.snapshot(evaluated_geometry=True)
            result['whole_seconds'] = round(time.perf_counter() - began, 3)
            result['whole_adapter_timing'] = (whole.get('_evaluated_data') or {}).get('timing')
        finally:
            evaluated.capture = real
        slow = meshes(whole)
        result['same_meshes'] = fast == slow
        result['differing'] = sorted(k for k in set(fast) | set(slow) if fast.get(k) != slow.get(k))[:20]
except Exception:
    result['error'] = traceback.format_exc()
save()
