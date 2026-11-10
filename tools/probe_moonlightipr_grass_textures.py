# python
"""GUI: MoonLightIPR on a scene whose textures overfill the graphics card (Grass by default, PROBE_SCENE for another).
A Render of SAMPLES a pixel, realtime off; the session's texture lines are kept (how many went to the computer's memory,
or were made smaller), with how long the scene took to reach its first picture and its last, the samples said, and the
picture as shown. Writes test-results/moonlightipr-grass/report.json and picture.png."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\moonlightipr-grass')
out.mkdir(parents=True, exist_ok=True)
SCENE = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\Grass\wildGreen_Patches_bundled.lxo')
SAMPLES = int(os.environ.get('PROBE_SAMPLES', '64'))
LIMIT = float(os.environ.get('PROBE_LIMIT', '600'))
result = {'scene': SCENE, 'samples_asked': SAMPLES, 'status': []}
state = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def lines():
    from moonray_modo import terminal
    found = []
    for entry in terminal.entries():
        found.extend(str(entry[4]).splitlines())
    return [line for line in found if 'MoonLightIPR' in line or 'texture' in line.lower() or 'memory' in line.lower()]


def begin():
    try:
        p = panel()
        result['kept_samples'] = p.preferences.get('moonlightipr/render_samples')
        p.preferences.set('moonlightipr/render_samples', SAMPLES)
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
        p.buffer.setCurrentIndex(p.buffer.findData('beauty'))
        state['began'] = time.monotonic()
        QtCore.QTimer.singleShot(1500, lambda: (p.start.click(), QtCore.QTimer.singleShot(500, wait)))
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def wait():
    try:
        p = panel()
        r = p.renderer
        said = getattr(r.moonlightipr, 'samples_now', None) if getattr(r, 'moonlightipr', None) else None
        status = p.status.text()
        if not result['status'] or result['status'][-1][1] != status:
            result['status'].append((round(time.monotonic() - state['began'], 1), status))
        if said and 'first_picture' not in result:
            result['first_picture'] = round(time.monotonic() - state['began'], 2)
        done = said and said[1] >= SAMPLES and not r.buffers.busy() and not getattr(p, '_rendering', False)
        if not done and time.monotonic() - state['began'] < LIMIT:
            QtCore.QTimer.singleShot(500, wait); return
        result['done'] = bool(done)
        result['seconds'] = round(time.monotonic() - state['began'], 2)
        result['samples'] = said
        result['label'] = p.image_info.text()
        p.preview.image.save(str(out / 'picture.png'))
    except Exception:
        result['error'] = traceback.format_exc()
    finish()


def finish():
    try:
        result['lines'] = lines()[-60:]
        p = panel()
        p.preferences.set('moonlightipr/render_samples', result.get('kept_samples') or 2000)
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('!scene.open {%s} normal' % SCENE)
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
