# python
"""Isolated GUI test: a heavy mesh read by the native adapter is the mesh the slow reader gives, and how much sooner.

MOONRAY_MODO_GEOMETRY names the adapter to test (build/modo-geometry-fast/MoonRayGeometry.lx). A dense ball with UVs,
two material tags and a second mesh of subdivision polygons are read both ways and compared value for value."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/mesh-reader'
out.mkdir(parents=True, exist_ok=True)
result = {}
SIDES = int(os.environ.get('PROBE_SIDES', '256'))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def ball(name, x, sides):
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    for key, value in (('cenX', x), ('cenY', 0.5), ('sizeX', 0.5), ('sizeY', 0.5), ('sizeZ', 0.5), ('sides', sides), ('segments', sides // 2)):
        lx.eval('tool.attr prim.sphere %s %s' % (key, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    mesh = modo.Scene().selected[0]
    mesh.name = name
    return mesh


def same(a, b, tolerance=1e-6):
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y, tolerance) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return abs(a - b) <= tolerance * max(1.0, abs(a))
    return a == b


try:
    from moonray_modo import host, mesh_reader
    result['adapter'] = [os.environ.get('MOONRAY_MODO_GEOMETRY', ''), mesh_reader.bridge() is not None]
    first = ball('Dense', 0.0, SIDES)
    with first.geometry as g:
        for index in range(0, len(g.polygons), 3):
            g.polygons[index].materialTag = 'Third'
    second = ball('Smooth', 2.0, 128)
    scene = modo.Scene()
    scene.select(second)
    lx.eval('select.typeFrom polygon')
    lx.eval('poly.convert face subpatch true')
    lx.eval('select.typeFrom item')
    result['polygons'] = {m.name: len(m.geometry.polygons) for m in (first, second)}
    save()
    keep = mesh_reader.THRESHOLD
    mesh_reader.THRESHOLD = 10 ** 12
    started = time.perf_counter()
    slow = host.snapshot()
    result['slow_seconds'] = round(time.perf_counter() - started, 2)
    save()
    mesh_reader.THRESHOLD = keep
    started = time.perf_counter()
    fast = host.snapshot()
    result['fast_seconds'] = round(time.perf_counter() - started, 2)
    result['meshes'] = [len(slow['meshes']), len(fast['meshes'])]
    import cProfile, io, pstats
    profile = cProfile.Profile()
    profile.enable()
    host.snapshot()
    profile.disable()
    text = io.StringIO()
    pstats.Stats(profile, stream=text).sort_stats('tottime').print_stats(22)
    (out / 'profile.txt').write_text(text.getvalue())
    checks = {}
    for a, b in zip(slow['meshes'], fast['meshes']):
        checks[a['name'] + '|' + a['identity'].split('|', 1)[1]] = {key: same(a.get(key), b.get(key)) for key in
            ('vertices', 'faces', 'uvs', 'normals', 'face_materials', 'uv_sets', 'subdivision', 'matrix', 'identity')}
        checks[a['name'] + '|' + a['identity'].split('|', 1)[1]]['sizes'] = [len(a['vertices']), len(a['faces']), len(a.get('uvs') or []), len(a.get('normals') or [])]
    result['same'] = checks
    result['all_same'] = all(v for entry in checks.values() for k, v in entry.items() if k != 'sizes')
    result['warnings'] = [slow.get('warnings'), fast.get('warnings')]
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
