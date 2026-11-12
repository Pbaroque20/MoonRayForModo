# python
"""GUI: MoonLightIPR's motion vectors gathered with every other AOV where something moves (panel._capture_preview). A
cube keyed to slide 2 units across 10 frames, seen at frame 5, motion blur off; a MoonLightIPR Render of 64 samples.
Then: whether the scene was read with the shutter's ends, Motion vectors chosen (it must come at once, no render begun
again) and the vectors' mean across the cube; with PROBE_STILL=1 the cube unkeyed instead (read once: no shutter's
ends, no vectors listed); and what Export AOVs lists. Writes test-results/moonlightipr-vectors-always[-still]/report.json."""
import json
import os
import pathlib
import struct
import time
import traceback
import lx
import modo
from PySide2 import QtCore

STILL = os.environ.get('PROBE_STILL') == '1'
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\moonlightipr-vectors-always' + ('-still' if STILL else ''))
out.mkdir(parents=True, exist_ok=True)
result = {}
state = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def build(keyed=True):
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Cube')
    with mesh.geometry as geo:
        c = [geo.vertices.new((a - .5, b - .5, d - .5)) for a in (0, 1) for b in (0, 1) for d in (0, 1)]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geo.polygons.new([c[i] for i in face])
    fps = float(scene.fps)
    for frame, x in (((0, -1.0), (10, 1.0)) if keyed else ()):
        mesh.position.x.set(x, time=frame / fps, key=True)
    lx.eval('select.time %g' % (5 / fps))
    camera = next(i for i in scene.items('camera'))
    scene.select(camera)
    for name, value in (('pos.X', 0), ('pos.Y', 0), ('pos.Z', 6), ('rot.X', 0), ('rot.Y', 0), ('rot.Z', 0)):
        lx.eval('transform.channel %s %s' % (name, value))
    render = scene.renderItem
    for name, value in (('resX', 320), ('resY', 180)):
        render.channel(name).set(value)
    state['mesh'] = mesh
    result['position_at_5' if keyed else 'still_position'] = [mesh.position.x.get(time=4 / fps), mesh.position.x.get(time=5 / fps), mesh.position.x.get(time=6 / fps)]


def begin():
    try:
        p = panel()
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
        p.buffer.setCurrentIndex(p.buffer.findData('beauty'))
        result['preview_motion'] = p.preferences.get('preview_motion')
        start_render('still' if STILL else 'moving')
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def start_render(label):
    p = panel()
    state['label'], state['began'] = label, time.monotonic()
    QtCore.QTimer.singleShot(1000, lambda: (p.start.click(), QtCore.QTimer.singleShot(500, wait_render)))


def wait_render():
    try:
        p = panel()
        r = p.renderer
        said = getattr(r.moonlightipr, 'samples_now', None)
        done = said and not r.buffers.busy() and not getattr(p, '_rendering', False) and r.buffers.progressive_frames.get('beauty')
        if not done and time.monotonic() - state['began'] < 180:
            QtCore.QTimer.singleShot(200, wait_render); return
        snapshot = r.buffers.progressive_scene or {}
        entry = {'seconds': round(time.monotonic() - state['began'], 2), 'samples': said, 'status': p.status.text(),
                 'motion_steps': snapshot.get('motion_steps')}
        result[state['label']] = entry
        save()
        # Motion vectors chosen: must come at once.
        before = (r.buffers.progressive_frames.get('motion_vectors') or {}).get('linear', {}).get('motion_vectors')
        state['asked'] = time.monotonic()
        state['before'] = before
        state['samples_before'] = said
        p.buffer.setCurrentIndex(p.buffer.findData('motion_vectors'))
        QtCore.QTimer.singleShot(100, wait_vectors)
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def wait_vectors():
    try:
        p = panel()
        r = p.renderer
        now = (r.buffers.progressive_frames.get('motion_vectors') or {}).get('linear', {}).get('motion_vectors')
        if (now is None or now is state['before']) and time.monotonic() - state['asked'] < 60:
            QtCore.QTimer.singleShot(100, wait_vectors); return
        entry = result[state['label']]
        entry['vectors_after'] = round(time.monotonic() - state['asked'], 2)
        entry['rendering_after_choice'] = bool(getattr(p, '_rendering', False))
        entry['samples_after_choice'] = getattr(r.moonlightipr, 'samples_now', None)
        if now is not None:
            width, height, pixels = now
            values = struct.unpack('<%df' % (width * height * 3), bytes(pixels))
            # Across and up, in pixels, where anything moves.
            moving = [(values[i * 3], values[i * 3 + 1]) for i in range(width * height) if abs(values[i * 3]) > 0.5 or abs(values[i * 3 + 1]) > 0.5]
            entry['moving_pixels'] = len(moving)
            if moving:
                entry['mean_vector'] = [round(sum(v[0] for v in moving) / len(moving), 2), round(sum(v[1] for v in moving) / len(moving), 2)]
        # What Export AOVs would offer.
        from moonray_modo import moonlightipr_aovs
        snapshot = r.buffers.progressive_scene or {}
        entry['export_lists_vectors'] = len(snapshot.get('motion_steps') or []) == 2
        save()
        p.buffer.setCurrentIndex(p.buffer.findData('beauty'))
        finish()
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def finish():
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    build(keyed=not STILL)
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
