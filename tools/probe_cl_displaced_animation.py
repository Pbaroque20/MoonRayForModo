# python
"""Command line: frames of an animation of a displaced 10 x 10 m plane (as tools/probe_cl_displaced_plane.py makes it),
read as Surfaces: Modo evaluated geometry reads it for MoonRay (Modo's displaced render cache), at a Displacement Rate
that keeps Modo's own cut (PROBE_RATE, 3 pixels): what the guard against too fine a cut (host.modo_cut_refused) costs
each frame. The scene is saved first (PROBE_OUT/animation.lxo), so that the Scene cache keeps its readings (PROBE_SAVE=0:
left unsaved, every reading made anew). On 2026-11-26, 1.3 M triangles at 3 pixels: 2.7 s a frame before the guard's
undisplaced reading had a place of its own in memory, 0.03 s after; unsaved, 2 undisplaced readings in 5 frames for 5. For each
frame of PROBE_FRAMES (8), with the camera still and then moving 2 cm a frame (PROBE_MOVES=still,moving): the reading's
seconds, the render cache readings made (displaced or not) and what the Scene cache did (geometry_cache.LAST). Writes
<PROBE_OUT>/report.json."""
import json
import math
import os
import pathlib
import time
import traceback

import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\displaced-animation'))
out.mkdir(parents=True, exist_ok=True)
bumps = pathlib.Path(os.environ.get('PROBE_BUMPS', str(out / 'bumps.png')))
segments = int(os.environ.get('PROBE_SEGMENTS', 4))
frames = int(os.environ.get('PROBE_FRAMES', 8))
report = {'segments': segments, 'frames': frames}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


try:
    scene = modo.Scene()
    lx.eval('item.create mesh')
    mesh = scene.selected[-1]
    size = 10.0
    with mesh.geometry as geometry:
        points = [[geometry.vertices.new((-size / 2 + size * i / segments, 0.0, -size / 2 + size * j / segments))
                   for i in range(segments + 1)] for j in range(segments + 1)]
        for j in range(segments):
            for i in range(segments):
                geometry.polygons.new((points[j][i], points[j + 1][i], points[j + 1][i + 1], points[j][i + 1]), reversed=False)
    render = scene.renderItem
    width = int(os.environ.get('PROBE_SIZE', 1920))
    render.channel('resX').set(width)
    render.channel('resY').set(width * 9 // 16)
    render.channel('dispRate').set(float(os.environ.get('PROBE_RATE', 3.0)))
    lx.eval('clip.addStill {%s}' % bumps)
    clip = next(c for c in scene.items('videoStill') if pathlib.Path(c.channel('filename').get()).name == bumps.name)
    base = next(i for i in render.children() if i.type == 'advancedMaterial')
    base.channel('displace').set(0.1)
    shader = next(i for i in render.children() if i.type == 'defaultShader')
    layer = scene.addItem('imageMap', name='bumps (Image)')
    layer.setParent(render, max(0, shader.parentIndex - 1))
    layer.channel('effect').set('displace')
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, clip._item)
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('planar')
    locator.channel('projAxis').set(1)
    locator.scale.set((2.5, 2.5, 2.5))
    camera = scene.renderCamera
    camera.position.set((0.0, 1.7, 4.5))
    camera.rotation.set((-math.radians(12.0), 0.0, 0.0))
    if os.environ.get('PROBE_SAVE', '1') == '1':
        saved = out / 'animation.lxo'
        lx.eval('scene.saveAs {%s} $LXOB false' % saved)
        report['saved'] = str(saved)

    from moonray_modo import host, evaluated, geometry_cache, displacement_budget
    captured = []
    original = evaluated.capture

    def counted(time_, path=None, displaced=True, only=None, before=None, kept=True, direct=True):
        began = time.perf_counter()
        try:
            return original(time_, path, displaced, only, before, kept, direct)
        finally:
            # Whole readings only (the kept path's own calls inside are its business).
            if only is None and before is None and kept:
                captured.append({'displaced': bool(displaced), 'seconds': round(time.perf_counter() - began, 3),
                                 'cache': {k: v for k, v in geometry_cache.LAST.items()
                                           if k in ('in_memory', 'quiet', 'render_cache', 'refused', 'read_again', 'seconds')}})
    evaluated.capture = counted
    guarded = []
    guard = host.modo_cut_refused

    def timed(*args, **kwargs):
        began = time.perf_counter()
        try:
            return guard(*args, **kwargs)
        finally:
            guarded.append(round(time.perf_counter() - began, 3))
    host.modo_cut_refused = timed
    fps = float(scene.fps or 24.0)
    for move in os.environ.get('PROBE_MOVES', 'still,moving').split(','):
        rows = []
        for frame in range(frames):
            lx.eval('select.time %f' % (frame / fps))
            if move == 'moving':
                camera.position.set((0.0, 1.7, 4.5 - 0.02 * frame))
            held = geometry_cache.estimate_session()
            heard_before = None if held is None else {'everything': held.get('everything'), 'edited': sorted(
                '%s (%s)' % (i, scene.item(i).type) for i in held.get('edited') or ())}
            del captured[:]
            del guarded[:]
            began = time.perf_counter()
            with host.by_engine('moonray'):
                snapshot = host.snapshot(evaluated_geometry=True)
            rows.append({'frame': frame, 'seconds': round(time.perf_counter() - began, 3),
                         'undisplaced_reads': sum(1 for c in captured if not c['displaced']),
                         'displaced_reads': sum(1 for c in captured if c['displaced']), 'reads': list(captured),
                         'guard_seconds': sum(guarded),
                         'heard_before': heard_before,
                         # What the estimate's sample has heard of since (host.estimate_sample): edits read it again.
                         'heard_after': (lambda held: None if held is None else {
                             'everything': held.get('everything'),
                             'edited': sorted('%s (%s)' % (i, scene.item(i).type) for i in held.get('edited') or ())})(
                             geometry_cache.estimate_session()),                         'faces': sum(len(m.get('faces') or []) for m in snapshot.get('meshes') or []),
                         'refused': any('Displacement Rate' in w for w in snapshot.get('warnings') or [])})
            report[move] = rows
            save()
        report[move + '_total_seconds'] = round(sum(r['seconds'] for r in rows), 3)
        report[move + '_undisplaced_reads'] = sum(r['undisplaced_reads'] for r in rows)
    evaluated.capture = original
except Exception:
    report['error'] = traceback.format_exc()
save()
