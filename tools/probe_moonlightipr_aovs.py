# python
"""GUI: MoonLightIPR's AOVs (moonlightipr_aovs). A Render of 64 samples a pixel, realtime off, then each AOV chosen in
the buffer list in turn: the session renders again with it, and its frame comes under its own key. For each: the mean
of its raw floats (from the frame the kit holds), how long it took, and the picture as shown, as PNG. The light passes
are checked to add up to the beauty. Writes test-results/moonlightipr-aovs/aovs.json. PROBE_SCENE picks the scene."""
import json
import os
import pathlib
import struct
import time
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\moonlightipr-aovs')
out.mkdir(parents=True, exist_ok=True)
result = {'aovs': {}}
SAMPLES = 64
KEYS = ['beauty', 'moonlightipr_diffuse', 'moonlightipr_glossy', 'emission', 'environment_background', 'alpha', 'depth',
        'normal', 'position', 'albedo']
state = {'index': 0}


def save():
    (out / 'aovs.json').write_text(json.dumps(result, indent=1, default=str))


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def mean(pixels):
    count = len(pixels) // 12
    values = struct.unpack('<%df' % (count * 3), pixels[:count * 12])
    return [round(sum(values[c::3]) / count, 6) for c in range(3)]


def begin():
    try:
        p = panel()
        result['kept_samples'] = p.preferences.get('moonlightipr/render_samples')
        p.preferences.set('moonlightipr/render_samples', SAMPLES)
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
        p.buffer.setCurrentIndex(p.buffer.findData('beauty'))
        result['listed'] = [p.buffer.itemData(i) for i in range(p.buffer.count()) if not p.buffer.view().isRowHidden(i)]
        QtCore.QTimer.singleShot(1500, lambda: (p.start.click(), QtCore.QTimer.singleShot(500, wait_key)))
        state['began'] = time.monotonic()
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def wait_key():
    try:
        p = panel()
        key = KEYS[state['index']]
        r = p.renderer
        said = getattr(r.moonlightipr, 'samples_now', None)
        frame = r.buffers.progressive_frames.get(key) or (r.buffers.frame if key == 'beauty' else None)
        linear = (frame or {}).get('linear', {}).get(key)
        done = said and said[1] >= SAMPLES and linear is not None and not r.buffers.busy() and not getattr(p, '_rendering', False)
        if not done and time.monotonic() - state['began'] < 90:
            QtCore.QTimer.singleShot(200, wait_key); return
        entry = {'seconds': round(time.monotonic() - state['began'], 2), 'label': p.image_info.text(), 'status': p.status.text(),
                 'samples': said}
        if linear is not None:
            entry['mean'] = mean(linear[2])
        else:
            entry['missing'] = True
        p.preview.image.save(str(out / (key + '.png')))
        result['aovs'][key] = entry
        save()
        state['index'] += 1
        if state['index'] >= len(KEYS):
            finish(); return
        nxt = KEYS[state['index']]
        state['began'] = time.monotonic()
        p.buffer.setCurrentIndex(p.buffer.findData(nxt))
        QtCore.QTimer.singleShot(500, wait_key)
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def finish():
    try:
        p = panel()
        p.preferences.set('moonlightipr/render_samples', result.get('kept_samples') or 500)
        p.buffer.setCurrentIndex(p.buffer.findData('beauty'))
        a = result['aovs']
        parts = ['moonlightipr_diffuse', 'moonlightipr_glossy', 'emission', 'environment_background']
        if all(k in a and 'mean' in a[k] for k in parts + ['beauty']):
            result['sum_of_passes'] = [round(sum(a[k]['mean'][c] for k in parts), 6) for c in range(3)]
            result['beauty_mean'] = a['beauty']['mean']
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('!scene.open {%s} normal' % os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\src.lxo'))
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
