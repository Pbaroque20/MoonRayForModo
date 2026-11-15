# python
"""Command line: what a camera move costs MoonLightIPR in a scene with replicators (PROBE_SCENE). The scene is read as
realtime reads it (Modo's evaluated geometry), the camera moved, and the camera-only update made as the preview makes
it: the reading with the meshes kept (host.snapshot reuse_geometry), then MoonLightIPR's packing (moonlightipr_scene.pack).
Each is timed three times, then profiled; the busiest calls by their own time and by their total are kept, with how
many meshes and placements the scene holds. Writes PROBE_OUT/report.json (test-results/replicator-camera-move)."""
import cProfile
import json
import os
import pathlib
import pstats
import time
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\replicator-camera-move'))
out.mkdir(parents=True, exist_ok=True)
result = {'scene': os.environ.get('PROBE_SCENE')}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def busiest(profile, count=20):
    stats = pstats.Stats(profile).stats
    rows = [(path.replace('\\', '/').split('/')[-1], name, nc, round(tt, 4), round(ct, 4)) for (path, _l, name), (_cc, nc, tt, ct, _c) in stats.items()]
    return {'own': sorted(rows, key=lambda r: -r[3])[:count], 'total': sorted(rows, key=lambda r: -r[4])[:count]}


def timed(label, work):
    times = []
    for _ in range(3):
        start = time.perf_counter()
        value = work()
        times.append(round(time.perf_counter() - start, 4))
    profile = cProfile.Profile()
    profile.enable()
    work()
    profile.disable()
    result[label] = {'seconds': times, 'profile': busiest(profile)}
    save()
    return value


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    import modo
    from moonray_modo import host, moonlightipr_scene
    start = time.perf_counter()
    first = host.snapshot(evaluated_geometry=True)
    result['first_reading'] = round(time.perf_counter() - start, 3)
    meshes = first.get('meshes') or []
    result['meshes'] = len(meshes)
    result['placements'] = sum(len(m.get('instances') or [1]) for m in meshes)
    result['instanced_meshes'] = sum(1 for m in meshes if m.get('instances'))
    result['triangles'] = sum(len(m.get('faces') or m.get('triangles') or ()) for m in meshes)
    save()
    cache = dict(first, meshes=[dict(m) for m in meshes])
    camera = modo.Scene().renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    position = camera.position
    position.set((position.get()[0] + 0.5, position.get()[1], position.get()[2]))
    scene = timed('camera_reading', lambda: host.snapshot(evaluated_geometry=True, reuse_geometry=cache))
    timed('moonlightipr_pack', lambda: moonlightipr_scene.pack(scene, 640, 360, 0.15, (), 16, False, None))
    # What the preview does next for MoonLightIPR's motion vectors: the shutter's ends asked of where the items stand
    # (None where the scene is not rigid), then, where that cannot tell, the whole scene read at the shutter's ends.
    from moonray_modo import animation, incremental
    from moonray_modo.motion import moves
    result['steady'] = incremental.steady(modo.Scene())
    result['rigid'] = incremental.rigid(modo.Scene(), scene)
    result['kinds'] = sorted({item.type for item in modo.Scene().items()})
    result['shutter_moves'] = timed('shutter_moves', lambda: animation.shutter_moves(scene, True))
    held = timed('capture_current', lambda: animation.capture_current(True))
    result['capture_current_moves'] = bool(moves(held))
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
