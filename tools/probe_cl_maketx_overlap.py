# python
"""Command line: PROBE_SCENE written for MoonRay (rdla.scene_text) and packed for MoonLightIPR, each with an empty
texture cache, every converter run (maketx, oiiotool) timed: how many ran at once at most, and in which thread, to see
whether the scene's textures are converted side by side (conversions.together). Writes PROBE_OUT/report.json
(test-results/maketx-overlap). Run with MOONRAY_MODO_CACHE set to an empty folder."""
import json
import os
import pathlib
import subprocess
import threading
import time
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\maketx-overlap'))
out.mkdir(parents=True, exist_ok=True)
result = {'scene': os.environ.get('PROBE_SCENE'), 'cache': os.environ.get('MOONRAY_MODO_CACHE')}
runs = []
held_run = subprocess.run


def timed(args, *rest, **named):
    name = os.path.basename(str(args[0])) if isinstance(args, (list, tuple)) and args else str(args)[:40]
    start = time.perf_counter()
    try:
        return held_run(args, *rest, **named)
    finally:
        if name.lower().startswith(('maketx', 'oiiotool')):
            runs.append((name, start, time.perf_counter(), threading.current_thread().name))


def summary(found, zero):
    events = sorted([(s, 1) for _, s, _, _ in found] + [(e, -1) for _, _, e, _ in found])
    most = now = 0
    for _, step in events:
        now += step
        most = max(most, now)
    return {'runs': len(found), 'most_at_once': most, 'threads': sorted({t for *_, t in found}),
            'seconds': round(max((e for _, _, e, _ in found), default=zero) - zero, 2),
            'busy_seconds': round(sum(e - s for _, s, e, _ in found), 2)}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    subprocess.run = timed
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import host, rdla, scene_setup, moonlightipr_scene, native
    from moonray_modo import cache_folder
    cache_folder._HELD['root'] = pathlib.Path(os.environ['MOONRAY_MODO_CACHE'])  # an empty cache: every texture converted
    scene = host.snapshot()
    scene_setup.configure(scene, scene_setup.values())
    start = time.perf_counter()
    rdla.scene_text(scene, 640, 360, 1, 0.2)
    result['moonray'] = summary(list(runs), start)
    result['moonray']['scene_seconds'] = round(time.perf_counter() - start, 2)
    save()
    runs.clear()
    start = time.perf_counter()
    moonlightipr_scene.pack(scene, 960, 540, 0.15, set(), 16, False, native.default_runtime() if hasattr(native, 'default_runtime') else None)
    result['moonlightipr'] = summary(list(runs), start)
    result['moonlightipr']['scene_seconds'] = round(time.perf_counter() - start, 2)
except Exception:
    result['error'] = traceback.format_exc()
finally:
    subprocess.run = held_run
save()
lx.eval('!app.quit')
