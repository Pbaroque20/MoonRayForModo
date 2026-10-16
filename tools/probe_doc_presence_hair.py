# python
"""Isolated GUI test, for the docs: the Render item's Bounces and Noise and Filtering sections, with Sample Hair Lobes
Separately, Presence Quality and Cryptomatte Multi-Presence.

The Render item is selected and Modo's own window pictured; the window is then made taller than the screen and pictured
again, for the panel's lower sections. Every scroll bar seen is written down."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/doc-presence-hair'
out.mkdir(parents=True, exist_ok=True)
result = {}


def window():
    shown = [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()]
    return max(shown, key=lambda w: w.width() * w.height())


def bars():
    main = window()
    found = []
    for bar in main.findChildren(QtWidgets.QScrollBar):
        if bar.isVisible() and bar.orientation() == QtCore.Qt.Vertical and bar.maximum() > 0:
            corner = bar.mapTo(main, QtCore.QPoint(0, 0))
            found.append((bar, corner.x(), corner.y(), bar.height(), bar.maximum()))
    return found


def scrolled():
    try:
        window().grab().save(str(out / 'end.png'))
    except Exception:
        result['end_error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


def first():
    try:
        window().grab().save(str(out / 'top.png'))
        found = bars()
        result['bars'] = [entry[1:] for entry in found]
        right = [entry for entry in found if entry[1] > window().width() * 0.8]
        if right:
            bar = max(right, key=lambda entry: entry[3])[0]
            bar.setValue(bar.maximum())
        else:
            # Modo draws its own scroll bars and reads no wheel sent to it; the window is made taller than the
            # screen instead, so that the panel shows its lower sections.
            main = window()
            main.showNormal()
            main.setGeometry(main.x(), 0, main.width(), 1800)
            result['tall'] = [main.width(), main.height()]
    except Exception:
        result['error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(1500, scrolled)


try:
    scene = modo.Scene()
    lx.eval('select.item {%s} set' % scene.renderItem.id)
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(5000, first)
