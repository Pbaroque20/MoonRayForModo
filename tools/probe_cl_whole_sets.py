# python
"""Command line: a scene's textures' own UVs read for whole meshes at once (host.WHOLE_MESH_SETS) against a polygon at a
time, for every mesh: the same numbers, and how long each reading took. MOONRAY_PROBE_SCENE; writes
test-results/whole-sets.json."""
import json
import os
import pathlib
import time
import traceback
import lx

result = {}
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    from moonray_modo import host

    def reading(whole):
        host.WHOLE_MESH_SETS = whole
        began = time.perf_counter()
        shot = host.snapshot()
        return shot, time.perf_counter() - began
    reading(True)       # warm: the first reading of a session pays for what later ones keep
    polygon, took_polygon = reading(False)
    each, took_whole = reading(True)
    import cProfile, io, pstats
    profile = cProfile.Profile()
    profile.enable()
    reading(True)
    profile.disable()
    text = io.StringIO()
    pstats.Stats(profile, stream=text).sort_stats('cumulative').print_stats(30)
    pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\whole-sets-profile.txt').write_text(text.getvalue())
    result['seconds'] = {'whole': round(took_whole, 2), 'polygon': round(took_polygon, 2)}
    compared, worst, differ = 0, 0.0, []
    by_identity = {m['identity']: m for m in polygon['meshes']}
    for mesh in each['meshes']:
        other = by_identity.get(mesh['identity'])
        if other is None:
            differ.append(('missing', mesh['identity']))
            continue
        for name in ('faces', 'face_materials'):
            if list(map(list, mesh.get(name) or [])) != list(map(list, other.get(name) or [])) if name == 'faces' else \
                    list(mesh.get(name) or []) != list(other.get(name) or []):
                differ.append((name, mesh['name']))
        for name in ('uvs', 'normals'):
            x, y = list(mesh.get(name) or []), list(other.get(name) or [])
            if len(x) != len(y) or any(abs(p[i] - q[i]) > 1e-5 for p, q in zip(x, y) for i in range(len(p))):
                differ.append((name, mesh['name'], len(x), len(y)))
        a, b = mesh.get('uv_sets') or {}, other.get('uv_sets') or {}
        if sorted(a) != sorted(b):
            differ.append(('keys', mesh['name'], sorted(a), sorted(b)))
            continue
        for key in a:
            x, y = list(a[key]), list(b[key])
            if len(x) != len(y):
                differ.append(('length', mesh['name'], key, len(x), len(y)))
                continue
            gap = max((abs(p[i] - q[i]) for p, q in zip(x, y) for i in (0, 1)), default=0.0)
            worst = max(worst, gap)
            compared += len(x)
            if gap > 1e-4:
                differ.append(('values', mesh['name'], key, gap))
    result['slow_reads'] = dict(host.SLOW_READS)
    result['small_meshes'] = sorted((len(m['faces']), m['name']) for m in each['meshes'] if len(m['faces']) < 5000)[-15:]
    result.update(compared_corners=compared, worst=worst, differ=differ[:20],
                  meshes_with_sets=sum(1 for m in each['meshes'] if m.get('uv_sets')))
except Exception:
    result['error'] = traceback.format_exc()
pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\whole-sets.json').write_text(json.dumps(result, indent=1, default=str))
