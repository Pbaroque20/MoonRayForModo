# python
"""Isolated GUI test: where the time goes when the preview reads a scene that has an imported MaterialX material on a dense mesh.
The whole read, and the reads IPR makes while following, are timed and the whole read is profiled."""
import cProfile
import io
import json
import os
import pathlib
import pstats
import time
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/capture-time'
out.mkdir(parents=True, exist_ok=True)
result = {}
import faulthandler
_fault = open(str(out / 'stacks.log'), 'w')
# Where it is, should it stop answering.
faulthandler.dump_traceback_later(40, repeat=True, file=_fault)
SOURCE = os.environ.get('PROBE_MTLX', '')


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def timed(call, repeat=2):
    times = []
    for _ in range(repeat):
        started = time.perf_counter()
        value = call()
        times.append(round(time.perf_counter() - started, 3))
    return times, value


try:
    from moonray_modo import host
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    for key, value in (('cenY', 0.5), ('sizeX', 0.5), ('sizeY', 0.5), ('sizeZ', 0.5), ('sides', int(os.environ.get('PROBE_SIDES', '96'))), ('segments', int(os.environ.get('PROBE_SIDES', '96')) // 2)):
        lx.eval('tool.attr prim.sphere %s %s' % (key, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    scene = modo.Scene()
    mesh = scene.selected[0]
    result['polygons'] = len(mesh.geometry.polygons)
    save()
    result['plain'], _ = timed(host.snapshot)
    save()
    scene.select(mesh)
    started = time.perf_counter()
    lx.eval('moonray.material.importMaterialX {%s}' % SOURCE)
    result['import'] = round(time.perf_counter() - started, 3)
    save()
    result['stage'] = 'reading with the material'
    save()
    result['with_materialx'], snapshot = timed(host.snapshot)
    save()
    result['uv_sets'] = {m['name']: len(m.get('uv_sets') or {}) for m in snapshot['meshes']}
    profile = cProfile.Profile()
    profile.enable()
    host.snapshot()
    profile.disable()
    text = io.StringIO()
    pstats.Stats(profile, stream=text).sort_stats('cumulative').print_stats(45)
    (out / 'profile.txt').write_text(text.getvalue())
    save()
    # What IPR does between whole reads: the kept geometry, with the materials read again.
    cache = dict(snapshot, meshes=[dict(m) for m in snapshot['meshes']])
    result['materials_only'], _ = timed(lambda: host.snapshot(reuse_geometry=cache, refresh_materials=True))
    result['reused'], _ = timed(lambda: host.snapshot(reuse_geometry=cache))
    from moonray_modo import moonlightipr_scene, native, properties, scene_settings
    result['settings'], _ = timed(lambda: scene_settings.complete(properties.scene_settings()), 5)
except BaseException:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
