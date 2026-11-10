# python
"""GUI: Render with MoonLightIPR, realtime off. The Render button is not greyed; a Render gathers Render samples a pixel
(moonlightipr/render_samples, set to 64 here, put back after) and stops; the label under the picture says the samples a
pixel as the picture comes ("n / 64 ps"). Writes test-results/moonlightipr-render-once.json, and the picture as PNG."""
import json
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results')
result = {'labels': []}
SAMPLES = 64


def save():
    (out / 'moonlightipr-render-once.json').write_text(json.dumps(result, indent=1, default=str))


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def begin():
    try:
        p = panel()
        result['kept_samples'] = p.preferences.get('moonlightipr/render_samples')
        p.preferences.set('moonlightipr/render_samples', SAMPLES)
        if p.ipr_mode.isChecked():
            p.ipr_mode.setChecked(False)
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
        QtCore.QTimer.singleShot(1500, press)
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def press():
    try:
        p = panel()
        result['before'] = {'enabled': p.start.isEnabled(), 'text': p.start.text(), 'tip': p.start.toolTip(),
                            'label': p.image_info.text()}
        result['began'] = time.monotonic()
        p.renderer.moonlightipr.output.connect(lambda text: result.setdefault('session_out', []).append(text[-400:]))
        p.status_texts = []
        if __import__('os').environ.get('PROBE_RT'):
            # Realtime instead: RT on, watched for as long as a render would be.
            p.renderer.moonlightipr.output.connect(lambda text: result.setdefault('session_out', []).append(text[-400:]))
            p.rt.setChecked(True)
            QtCore.QTimer.singleShot(25000, rt_done); return
        p.start.click()
        QtCore.QTimer.singleShot(300, watch)
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def watch():
    try:
        p = panel()
        label = p.image_info.text()
        if not result['labels'] or result['labels'][-1][1] != label:
            result['labels'].append((round(time.monotonic() - result['began'], 2), label, p.start.text()))
        if getattr(p, '_rendering', False) and time.monotonic() - result['began'] < 180:
            QtCore.QTimer.singleShot(200, watch); return
        if 'fail' in p.status.text().lower() or 'exited' in p.status.text().lower() or 'cannot' in p.status.text().lower():
            result['done_at'] = -100   # a failure: nothing more to wait for
        # Done: the picture may still be on its way to the screen (its conversion); waited for, up to 20 s.
        result.setdefault('done_at', round(time.monotonic() - result['began'], 2))
        shown = getattr(p.preview, 'image', None) is not None and not p.preview.image.isNull() and p.image_info.text()
        if not (shown and not p.renderer.buffers.busy() and getattr(p.renderer, 'moonlightipr_frame', None) is None)                 and time.monotonic() - result['began'] < result['done_at'] + 20:
            QtCore.QTimer.singleShot(200, watch); return
        r = p.renderer
        result['state'] = {'frames_shown': getattr(r, 'frames_shown', None), 'pending': getattr(r, 'moonlightipr_frame', None) is not None,
                           'busy': r.buffers.busy(), 'using': getattr(r, 'using_moonlightipr', None), 'serial': getattr(r, 'moonlightipr_serial', None),
                           'newest': getattr(r, 'moonlightipr_newest', None), 'current': getattr(r.moonlightipr, 'current', None),
                           'image_null': p.preview.image.isNull() if getattr(p.preview, 'image', None) is not None else 'no image',
                           'held': getattr(p, '_held', None), 'draft_fine': getattr(p, '_draft_fine', None)}
        try:
            from moonray_modo import terminal
            result['terminal'] = str(getattr(terminal, 'LOG', ''))[-3000:]
        except Exception as error:
            result['terminal'] = str(error)
        result['after'] = {'seconds': round(time.monotonic() - result['began'], 2), 'enabled': p.start.isEnabled(),
                           'text': p.start.text(), 'label': p.image_info.text(), 'status': p.status.text(),
                           'session_samples': getattr(p.renderer.moonlightipr, 'samples_now', None)}
        p.preview.image.save(str(out / 'moonlightipr-render-once.png'))
    except Exception:
        result['error'] = traceback.format_exc()
    finish()


def rt_done():
    try:
        p = panel()
        result['after'] = {'label': p.image_info.text(), 'status': p.status.text(), 'session_samples': getattr(p.renderer.moonlightipr, 'samples_now', None)}
        p.rt.setChecked(False)
    except Exception:
        result['error'] = traceback.format_exc()
    finish()


def finish():
    try:
        panel().preferences.set('moonlightipr/render_samples', result.get('kept_samples') or 500)
    except Exception:
        pass
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    import os
    lx.eval('!scene.open {%s} normal' % os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\src.lxo'))
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
