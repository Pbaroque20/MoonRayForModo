# python
"""Command line: whether a scene's meshes are bent by a rig, and what that costs. PROBE_SCENE the .lxo. Counts the
scene's items by type; for each mesh, its points as stored and as Modo's deformers leave them (the 'deformed' mesh
channel, as the kit reads it), how far apart the two lie at most and on average, the bounds of each, and how long the
deformed reading takes. Writes test-results/rig-check/report.json (PROBE_OUT for another folder)."""
import json
import os
import pathlib
import time
import traceback

import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\rig-check'))
out.mkdir(parents=True, exist_ok=True)
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def points(mesh):
    found = []
    point = mesh.PointAccessor()
    for k in range(mesh.PointCount()):
        point.SelectByIndex(k)
        found.append(point.Pos())
    return found


def bounds(values):
    return [[round(min(p[i] for p in values), 3) for i in range(3)], [round(max(p[i] for p in values), 3) for i in range(3)]]


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    scene = modo.Scene()
    counts = {}
    for item in scene.items():
        counts[item.type] = counts.get(item.type, 0) + 1
    report['types'] = dict(sorted(counts.items(), key=lambda kv: -kv[1]))
    save()
    meshes = []
    for item in scene.items('mesh'):
        entry = {'name': item.name}
        stored = [tuple(v.position) for v in item.geometry.vertices]
        began = time.perf_counter()
        deformed_mesh = modo.meshgeometry.MeshProvider.meshFromMeshChannel(item._item, 'deformed')
        deformed = points(deformed_mesh)
        entry['deformed_seconds'] = round(time.perf_counter() - began, 3)
        began = time.perf_counter()
        again = points(modo.meshgeometry.MeshProvider.meshFromMeshChannel(item._item, 'deformed'))
        entry['deformed_again_seconds'] = round(time.perf_counter() - began, 3)
        moved = [sum((a - b) ** 2 for a, b in zip(p, q)) ** .5 for p, q in zip(stored, deformed)]
        entry.update(points=len(stored), stored_bounds=bounds(stored), deformed_bounds=bounds(deformed),
                     most_moved=round(max(moved), 4), mean_moved=round(sum(moved) / len(moved), 4),
                     moved_over_1=sum(1 for m in moved if m > 1.0))
        meshes.append(entry)
        save()
    report['meshes'] = meshes
except Exception:
    report['error'] = traceback.format_exc()
save()
