# python
"""Isolated GUI test: MoonRay's time per pixel as a buffer of the preview. Two balls are rendered with MoonRay, the
Time per pixel buffer is chosen, and the picture's brightness is written down with the window's picture."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/time-per-pixel'
out.mkdir(parents=True, exist_ok=True)
result = {}


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def render():
    try:
        panel = panel_widget()
        panel.preferences.set('runtime', os.environ.get('MOONRAY_MODO_RUNTIME', ''))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(40000, choose)


def choose():
    try:
        panel = panel_widget()
        result['menu_has_it'] = panel.buffer.findText('Time per pixel') >= 0
        panel.buffer.setCurrentIndex(panel.buffer.findText('Time per pixel'))
    except Exception:
        result['error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(5000, finish)


def finish():
    try:
        panel = panel_widget()
        image = panel.preview.image.convertToFormat(QtGui.QImage.Format_RGB888)
        values = [image.pixelColor(x, y) for y in range(0, image.height(), 4) for x in range(0, image.width(), 4)]
        result.update(buffer=panel.buffer.currentData(), status=panel.status.text()[:90], image_null=panel.preview.image.isNull(),
                      grey=all(c.red() == c.green() == c.blue() for c in values),
                      levels=sorted({c.red() for c in values})[:3] + sorted({c.red() for c in values})[-3:])
        panel.preview.grab().save(str(out / 'time_per_pixel.png'))
        panel.stop()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


try:
    for x, tag, colour in ((-0.6, 'Red', '{1.0 0.0 0.0}'), (0.6, 'Green', '{0.0 1.0 0.0}')):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
        lx.eval('poly.setMaterial %s %s 0.8 0.04 true false' % (tag, colour))
    lx.eval('moonray.render.samples 4')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(15000, render)
