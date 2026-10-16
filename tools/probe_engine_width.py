# python
"""Isolated GUI test: the preview window's engine list shows MoonLightIPR whole, however narrow the window.

MoonLightIPR is chosen in the engine list; the preview window is made narrow, then wide, and its toolbar pictured
each time, with the list's width and the width its longest name needs."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/engine-width'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def shoot(name, width):
    panel = held['panel']
    window = panel.window()
    window.resize(width, window.height())
    QtWidgets.QApplication.processEvents()
    engine = panel.preview_engine
    result[name] = {'window': window.width(), 'list': engine.width(),
                    'needs': engine.fontMetrics().horizontalAdvance(engine.currentText()), 'shown': engine.currentText()}
    top = engine.mapTo(panel, QtCore.QPoint(0, 0)).y()
    panel.grab(QtCore.QRect(0, max(0, top - 4), panel.width(), engine.height() + 8)).save(str(out / (name + '.png')))


def begin():
    try:
        panel = held['panel'] = panel_widget()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
        QtWidgets.QApplication.processEvents()
        shoot('narrow', 500)
        shoot('wide', 1000)
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(6000, begin)
