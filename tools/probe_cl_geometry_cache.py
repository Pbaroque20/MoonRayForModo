# python
"""Command line: the geometry cache across Modo's sessions (geometry_cache). One run of three, by MOONRAY_PROBE_MODE,
each in a Modo of its own, on MOONRAY_PROBE_SCENE, with a cache folder of the probe's own
(test-results/geometry-cache/<label>/cache):
- first: the folder emptied, a whole reading, kept.
- edit: one mesh moved 1 mm (unsaved), a reading by way of the kept one, then a whole reading from Modo
  (kept=False) to compare every mesh with.
- same: nothing changed, a reading by way of the kept one.
- shape: one point of the largest mesh moved 1 cm, then as edit.
- session: in one Modo, read twice (disk, then memory), reshape a mesh, read again, compare; then close the scene.
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


def triangles(data, identity):
    found = []
    for proto in (data.get('prototypes') or {}).values():
        if proto.get('item') != identity:
            continue
        for segment in proto['segments']:
            verts = list(segment['vertices'])
            normals = list(segment['normals']) if segment['normals'] else []
            uvs = [list(s) for s in segment['uv_sets']]
            c = 0
            for face in segment['faces']:
                face = list(face)
                found.append((proto.get('material'), tuple(sorted(
                    (tuple(round(v, 5) for v in verts[i]), tuple(round(v, 5) for v in normals[c + k]) if normals else (),
                     tuple(tuple(round(v, 5) for v in s[c + k]) for s in uvs)) for k, i in enumerate(face)))))
                c += len(face)
    return sorted(found)


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
        # The mesh with the most polygons, which renders; for shape, the largest of those the kept reading says read
        # directly as the render cache gives them (geometry_cache.DIRECT).
        candidates = scene.items('mesh', superType=False)
        if mode == 'shape':
            held = geometry_cache.load(geometry_cache.key(lx.service.Selection().GetTime(), host.modo_displaces()))
            noted = set((held[1].get(geometry_cache.DIRECT) or {}) if held else ())
            result['noted_direct'] = len(noted)
            candidates = [m for m in candidates if m.id in noted] or candidates
        target = max(candidates, key=lambda m: m.geometry.numPolygons)
        if mode == 'edit':
            target.position.x.set(target.position.x.get() + 0.001)
        else:
            point = target.geometry.vertices[0]
            x, y, z = point.position
            point.position = (x + 0.01, y, z)
            target.geometry.setMeshEdits()
        result['edited'] = target.name
        result['changed_after_edit'] = int(lx.eval1('query sceneservice scene.changed ? current'))
    if mode == 'session':
        # In one Modo: read (from disk), read again (from memory, every mesh's tracker asked), reshape the largest
        # mesh read directly, read again; then as shape, and the scene closed at the end.
        steps = []
        for step in ('disk', 'memory'):
            began = time.perf_counter()
            if step == 'memory' and os.environ.get('MOONRAY_PROBE_PROFILE') == '1':
                import cProfile, io, pstats
                profile = cProfile.Profile()
                profile.enable()
                host.snapshot(evaluated_geometry=True)
                profile.disable()
                text = io.StringIO()
                pstats.Stats(profile, stream=text).sort_stats('cumulative').print_stats(45)
                (out / 'memory-profile.txt').write_text(text.getvalue(), encoding='utf-8')
            else:
                host.snapshot(evaluated_geometry=True)
            c = dict(geometry_cache.LAST)
            steps.append({'step': step, 'seconds': round(time.perf_counter() - began, 3), 'in_memory': c.get('in_memory'),
                          'digests_kept': c.get('digests_kept'), 'digests_seconds': c.get('digests_seconds'),
                          'render_cache': c.get('render_cache'), 'read_again': c.get('read_again'), 'quiet': c.get('quiet')})
        result['steps'] = steps
        save()
        mode_edit = 'shape'
    else:
        mode_edit = mode
    if mode == 'session':
        candidates = scene.items('mesh', superType=False)
        noted = set()
        for held in geometry_cache._SESSION.values():
            if held.get('held'):
                noted |= set(held['held'][1].get(geometry_cache.DIRECT) or {})
        target = max([m for m in candidates if m.id in noted] or candidates, key=lambda m: m.geometry.numPolygons)
        point = target.geometry.vertices[0]
        x, y, z = point.position
        point.position = (x + 0.01, y, z)
        target.geometry.setMeshEdits()
        result['edited'] = target.name
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
    if mode in ('edit', 'same', 'shape', 'session'):
        fast = meshes(shot)
        shot_data = shot.get('_evaluated_data') or {}
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
        if mode in ('shape', 'session'):
            # The edited mesh read directly: its triangles (points, normals, UVs) against the render cache's, as sets.
            mine = triangles(shot_data, target.id)
            theirs = triangles(whole.get('_evaluated_data') or {}, target.id)
            result['edited_triangles'] = [len(mine), len(theirs)]
            result['edited_same'] = mine == theirs
            fast = {k: v for k, v in fast.items() if not k.startswith(target.id + '|')}
            slow = {k: v for k, v in slow.items() if not k.startswith(target.id + '|')}
        differing = sorted(k for k in set(fast) | set(slow) if fast.get(k) != slow.get(k))
        # A mesh read directly comes in another order of triangles: compared as sets of triangles (points, normals,
        # UVs) with the render cache's.
        geometric = {}
        for key in differing:
            identity = key.split('|')[0]
            if identity not in geometric:
                geometric[identity] = triangles(shot_data, identity) == triangles(whole.get('_evaluated_data') or {}, identity)
        result['differing_by_order_only'] = sorted(i for i, same in geometric.items() if same)
        result['same_meshes'] = all(geometric.values())
        result['differing'] = sorted(i for i, same in geometric.items() if not same)[:20]
    if mode == 'session':
        lx.eval('scene.close')
        result['held_after_close'] = len(geometry_cache._SESSION)
except Exception:
    result['error'] = traceback.format_exc()
save()
