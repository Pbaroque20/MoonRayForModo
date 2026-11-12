# python
"""GUI: MoonLightIPR's motion vectors. A cube keyframed to slide along X (0 at frame 0, 10 at frame 2), seen at frame 1;
a Render of 64 samples a pixel, realtime off and motion blur off, with Motion vectors chosen: the scene is read with
the shutter's ends and held at the frame's moment. The vectors' raw floats: where they are not zero (the cube), their
mean across and up, and the background's. Then the beauty, to see it unblurred. Writes
test-results/moonlightipr-motion/vectors.json and PNGs."""
import json
import pathlib
import struct
import time
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\moonlightipr-motion')
out.mkdir(parents=True, exist_ok=True)
result = {}
state = {}


def save():
    (out / 'vectors.json').write_text(json.dumps(result, indent=1, default=str))


def build():
    import modo
    scene = modo.Scene()
    cube = scene.addMesh('Slider')
    with cube.geometry as geometry:
        corners = [geometry.vertices.new((x, y, z)) for x in (-1.0, 1.0) for y in (-1.0, 1.0) for z in (-1.0, 1.0)]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geometry.polygons.new([corners[i] for i in face])
    fps = float(scene.fps)
    for frame, x in ((0, 0.0), (2, 10.0)):
        cube.position.x.set(x, time=frame / fps, key=True)
    lx.eval('select.time %s' % (1 / fps))
    camera = scene.renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    for channel, value in (('pos.X', 5), ('pos.Y', 0), ('pos.Z', 20), ('rot.X', 0), ('rot.Y', 0)):
        lx.eval('transform.channel %s %s' % (channel, value))
    lx.eval('select.drop item')
    for name, value in (('resX', 480), ('resY', 270)):
        scene.renderItem.channel(name).set(value)
    result['cube_x_at_frames_0_1_2'] = [cube.position.x.get(time=f / fps) for f in (0, 1, 2)]


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def begin():
    try:
        p = panel()
        result['kept'] = (p.preferences.get('moonlightipr/render_samples'), p.preferences.get('preview_motion'))
        p.preferences.set('moonlightipr/render_samples', 64)
        p.preferences.set('preview_motion', False)
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
        p.buffer.setCurrentIndex(p.buffer.findData('motion_vectors'))
        result['listed_vectors'] = not p.buffer.view().isRowHidden(p.buffer.findData('motion_vectors'))
        state['began'] = time.monotonic()
        QtCore.QTimer.singleShot(1500, lambda: (p.start.click(), QtCore.QTimer.singleShot(1000, wait)))
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def wait():
    try:
        p = panel()
        r = p.renderer
        frame = r.buffers.progressive_frames.get('motion_vectors')
        linear = (frame or {}).get('linear', {}).get('motion_vectors')
        said = getattr(r.moonlightipr, 'samples_now', None)
        if not (linear and said and said[1] >= 64 and not getattr(p, '_rendering', False)) and time.monotonic() - state['began'] < 240:
            QtCore.QTimer.singleShot(300, wait); return
        result['status'] = p.status.text()
        result['label'] = p.image_info.text()
        result['hud'] = p._hud_words() if hasattr(p, '_hud_words') else None
        if linear:
            width, height, pixels = linear
            values = struct.unpack('<%df' % (width * height * 3), pixels)
            moving = [(values[i * 3], values[i * 3 + 1]) for i in range(width * height) if abs(values[i * 3]) > 1e-3 or abs(values[i * 3 + 1]) > 1e-3]
            result['pixels_moving'] = len(moving)
            if moving:
                result['mean_across'] = round(sum(m[0] for m in moving) / len(moving), 3)
                result['mean_up'] = round(sum(m[1] for m in moving) / len(moving), 3)
            result['corner_pixel'] = values[0:3]
        p.preview.image.save(str(out / 'vectors.png'))
        p.buffer.setCurrentIndex(p.buffer.findData('beauty'))
        state['began'] = time.monotonic()
        QtCore.QTimer.singleShot(1000, wait_beauty)
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def wait_beauty():
    try:
        p = panel()
        if getattr(p, '_rendering', False) and time.monotonic() - state['began'] < 120:
            QtCore.QTimer.singleShot(300, wait_beauty); return
        QtCore.QTimer.singleShot(1500, lambda: (p.preview.image.save(str(out / 'beauty.png')), finish()))
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def finish():
    try:
        p = panel()
        samples, blur = result.get('kept') or (500, False)
        p.preferences.set('moonlightipr/render_samples', samples or 500)
        p.preferences.set('preview_motion', bool(blur))
    except Exception:
        pass
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    build()
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
