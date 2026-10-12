# python
"""Isolated GUI test: how much of the picture MoonRay shows while it renders is too dark for a moment.

A scene (MOONRAY_PROBE_SCENE, else two balls) is previewed with MoonRay from the runtime named in MOONRAY_PROBE_RUNTIME,
under Safe Denoising if MOONRAY_PROBE_SAFE is set. The view is copied about twice a second while it renders, for up to
MOONRAY_PROBE_LIMIT seconds. A pixel caught part way through a sample is too dark in one copy and not in those to
either side of it: the share of pixels that dip so, markedly darker than in both the copy before and the copy after,
is worked out for every copy, and the worst copy is saved with the copies around it."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / ('test-results/dark-tiles' + ('-' + os.environ['MOONRAY_PROBE_LABEL'] if os.environ.get('MOONRAY_PROBE_LABEL') else ''))
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {'frames': [], 'times': []}
SAMPLES = int(os.environ.get('MOONRAY_PROBE_SAMPLES', '40'))
LIMIT = float(os.environ.get('MOONRAY_PROBE_LIMIT', '150'))
SAFE = bool(os.environ.get('MOONRAY_PROBE_SAFE'))
SCENE = os.environ.get('MOONRAY_PROBE_SCENE', '')


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin():
    try:
        panel = panel_widget()
        held['stored'] = [panel.preferences.store.value(key, None) for key in ('runtime', 'preview_engine', 'ipr')]
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0350-pool')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        if not panel._rendering:
            panel.start.click()
        held['began'] = time.monotonic()
    except Exception:
        result['error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(500, watch)


def watch():
    panel = panel_widget()
    image = panel.preview.image
    key = None if image.isNull() else image.cacheKey()
    if key is not None and key != held.get('last') and panel._rendering:
        held['last'] = key
        held['frames'].append(image.convertToFormat(QtGui.QImage.Format_RGB888).copy())
        held['times'].append(round(time.monotonic() - held['began'], 1))
        # No more than a hundred copies are kept: the newest, which are the ones compared.
        if len(held['frames']) > 100:
            held['frames'].pop(0); held['times'].pop(0)
    held['idle'] = 0 if panel._rendering else held.get('idle', 0) + 1
    if held['idle'] >= 3 or time.monotonic() - held['began'] > LIMIT:
        QtCore.QTimer.singleShot(200, finish)
        return
    QtCore.QTimer.singleShot(500, watch)


def finish():
    try:
        panel = panel_widget()
        result.update(safe=SAFE, loaded=bool(getattr(panel.renderer, 'using_session', False)), status=panel.status.text(), timing=panel.render_timing.text(),
                      rendering_at_end=panel._rendering)
        frames = held['frames']
        dips = []
        for index in range(1, len(frames) - 1):
            a, b, c = frames[index - 1], frames[index], frames[index + 1]
            if not (a.size() == b.size() == c.size()):
                dips.append(0.0)
                continue
            w, h, stride = b.width(), b.height(), b.bytesPerLine()
            before, now, after = bytes(a.constBits()), bytes(b.constBits()), bytes(c.constBits())
            dark = total = 0
            for y in range(0, h, 2):
                row = y * stride
                for x in range(0, w, 2):
                    i = row + x * 3 + 1
                    low = min(before[i], after[i])
                    if low > 24:
                        total += 1
                        # Under seven tenths of what it is on both sides: a dip, not noise settling.
                        if now[i] * 10 < low * 7:
                            dark += 1
            dips.append(dark / max(total, 1))
        # The first copies are coarse; they are left out.
        later = dips[4:] or dips
        offset = 4 if dips[4:] else 0
        if later:
            worst = max(range(len(later)), key=lambda i: later[i]) + offset + 1
            for name, index in (('before', worst - 1), ('worst', worst), ('after', worst + 1)):
                frames[index].save(str(out / (name + '.png')))
            result.update(frames=len(frames), size=[frames[worst].width(), frames[worst].height()], worst_at_seconds=held['times'][worst],
                          dip_share_percent={'mean': round(100 * sum(later) / len(later), 3), 'worst': round(100 * max(later), 3),
                                             'frames_over_a_twentieth_percent': sum(1 for s in later if s > .0005), 'frames_compared': len(later)})
        if panel._rendering:
            panel.renderer.stop(); panel._set_rendering(False)
        for key, value in zip(('runtime', 'preview_engine', 'ipr'), held['stored']):
            if value is None:
                panel.preferences.store.remove(key)
            else:
                panel.preferences.store.setValue(key, value)
    except Exception:
        result['finish_error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    lx.eval('!app.quit')


try:
    if SCENE:
        lx.eval('scene.open {%s} normal' % SCENE)
    else:
        for x in (-.6, .6):
            lx.eval('select.typeFrom item')
            lx.eval('item.create mesh')
            lx.eval('tool.set prim.sphere on')
            lx.eval('tool.attr prim.sphere cenX %s' % x)
            lx.eval('tool.apply')
            lx.eval('tool.set prim.sphere off')
        lx.eval('moonray.render.samples %d' % SAMPLES)
    if SAFE:
        lx.eval('moonray.render.denoiser 2')
        lx.eval('moonray.render.denoise_preview 1')
        lx.eval('moonray.render.denoise_safe 1')
    else:
        lx.eval('moonray.render.denoise_safe 0')
        if not SCENE:
            lx.eval('moonray.render.denoiser 0')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(8000, begin)
