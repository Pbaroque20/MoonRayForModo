# python
"""Isolated GUI test: how much of the picture MoonRay shows while it renders is too dark for a moment.

Two balls are previewed with MoonRay from the runtime named in MOONRAY_PROBE_RUNTIME. The view is copied about twice a
second while it renders, and once it has finished each copy is set against the finished picture: the share of pixels
that were markedly darker than they end up, which is what a pixel caught part way through a sample looks like. The
worst copy is saved."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/dark-tiles'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {'frames': []}
SAMPLES = int(os.environ.get('MOONRAY_PROBE_SAMPLES', '40'))


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
    except Exception:
        result['error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(500, watch)


def watch():
    panel = panel_widget()
    image = panel.preview.image
    key = None if image.isNull() else image.cacheKey()
    if key is not None and key != held.get('last') and panel.buffer.currentData() == 'beauty':
        held['last'] = key
        if len(held['frames']) < 60:
            held['frames'].append(image.convertToFormat(QtGui.QImage.Format_RGB888).copy())
    held['idle'] = 0 if panel._rendering else held.get('idle', 0) + 1
    held['ticks'] = held.get('ticks', 0) + 1
    if held['idle'] >= 3 or held['ticks'] > 300:
        panel.buffer.setCurrentIndex(panel.buffer.findData('beauty'))
        QtCore.QTimer.singleShot(2500, finish)
        return
    QtCore.QTimer.singleShot(500, watch)


def finish():
    try:
        panel = panel_widget()
        final = panel.preview.image.convertToFormat(QtGui.QImage.Format_RGB888).copy()
        final.save(str(out / 'final.png'))
        w, h, stride = final.width(), final.height(), final.bytesPerLine()
        last = bytes(final.constBits())
        shares = []
        for frame in held['frames']:
            if frame.size() != final.size():
                continue
            data = bytes(frame.constBits())
            dark = total = 0
            for y in range(0, h, 2):
                row = y * stride
                for x in range(0, w, 2):
                    i = row + x * 3 + 1
                    end = last[i]
                    if end > 40:
                        total += 1
                        # Markedly darker than it ends up: under three fifths of it.
                        if data[i] * 5 < end * 3:
                            dark += 1
            shares.append(dark / max(total, 1))
        # The first pictures are coarse and unlike the last in their own right: they are left out.
        later = shares[3:] or shares
        worst = max(range(len(later)), key=lambda i: later[i]) + (3 if shares[3:] else 0) if shares else None
        if worst is not None:
            held['frames'][worst].save(str(out / 'worst.png'))
        result.update(status=panel.status.text(), frames=len(shares), size=[w, h],
                      dark_share_percent={'mean': round(100 * sum(later) / max(len(later), 1), 3), 'worst': round(100 * max(later), 3) if later else None,
                                          'frames_over_a_tenth_percent': sum(1 for s in later if s > .001)})
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
    for x in (-.6, .6):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples %d' % SAMPLES)
    lx.eval('moonray.render.denoiser 0')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(8000, begin)
