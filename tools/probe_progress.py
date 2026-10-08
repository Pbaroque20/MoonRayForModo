# python
"""Isolated GUI test: render two cubes with a Cryptomatte output and picture its preview."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/progress'
out.mkdir(parents=True, exist_ok=True)
result = {}


def shot(name):
    for index, window in enumerate(w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.width() > 300):
        window.grab().save(str(out / ('%s-%d.png' % (name, index))))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


try:
    for x in (-0.7, 0.7):
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.cube on')
        lx.eval('tool.attr prim.cube cenX %s' % x)
        lx.eval('tool.attr prim.cube sizeX 1.0')
        lx.eval('tool.attr prim.cube sizeY 1.0')
        lx.eval('tool.attr prim.cube sizeZ 1.0')
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
    lx.eval('moonray.open')
    from moonray_modo import properties
except Exception:
    result['error'] = traceback.format_exc()
save()


def properties_now():
    from moonray_modo import properties
    return properties.scene_settings().get('custom_aovs')


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


shots = []


def step2():
    try:
        panel = panel_widget()
        result['engine'] = panel.preview_engine.currentData()
        result['runtime'] = panel.preferences.get('runtime')
        import os
        panel.preferences.set('runtime', str(root / 'runtime' / os.environ.get('PROBE_RUNTIME', 'steady-0349-candidate')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        lx.eval('moonray.render.sampling_mode 0')
        lx.eval('moonray.render.samples 12')
        lx.eval('moonray.render.execution_mode 2')
        panel.start.click()
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1500, grab)


def grab():
    try:
        panel = panel_widget()
        index = len(shots)
        panel.window().grab().save(str(out / ('pass-%02d.png' % index)))
        overlay = panel.preview.workers or panel.preview.buckets
        image = panel.preview.image
        if overlay and not image.isNull() and overlay[3]:
            _, width, height, rectangles = overlay
            x0, y0, x1, y1 = rectangles[0]
            cx, cy = int((x0 + x1) / 2), int(height - (y0 + y1) / 2)
            crop = image.copy(max(0, cx - 40), max(0, cy - 40), 80, 80)
            crop.scaled(640, 640, QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation).save(str(out / ('tile-%02d.png' % index)))
            result.setdefault('tiles', {})[index] = [rectangles[:4], [image.width(), image.height()], len(rectangles)]
        if not image.isNull() and index % 3 == 0:
            gray = image.convertToFormat(QtGui.QImage.Format_Grayscale8)
            line, w, h = gray.bytesPerLine(), gray.width(), gray.height()
            data = bytes(gray.constBits())[:line * h]
            specks = 0
            for y in range(1, h - 1):
                row, up, down = data[y * line:y * line + w], data[(y - 1) * line:(y - 1) * line + w], data[(y + 1) * line:(y + 1) * line + w]
                for x in range(1, w - 1):
                    v = row[x]
                    if abs(2 * v - row[x - 1] - row[x + 1]) > 24 and abs(2 * v - up[x] - down[x]) > 24:
                        specks += 1
            result.setdefault('specks', {})[index] = specks
        shots.append([panel.status.text(), panel.render_timing.text(), panel.start.text()])
        if index < 30 and panel.start.text() == 'Stop':
            QtCore.QTimer.singleShot(1000, grab)
            return
        result['shots'] = shots
        (out / 'render.log').write_text(panel.renderer.log or '', encoding='utf-8', errors='replace')
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(result['engine']))
        panel.preferences.set('runtime', result['runtime'])
    except Exception:
        result['grab_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(8000, step2)
