# python
"""GUI: the preview window's buffer list, as it shows, with MoonLightIPR the engine and then MoonRay: the rows not
hidden, in order. Writes test-results/buffer-order/report.json and a picture of the list open."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\buffer-order')
out.mkdir(parents=True, exist_ok=True)
result = {}


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def shown(p):
    return [p.buffer.itemText(i) for i in range(p.buffer.count()) if not p.buffer.view().isRowHidden(i)]


def engine(name, then):
    p = panel()
    p.preview_engine.setCurrentIndex(p.preview_engine.findData(name))
    QtCore.QTimer.singleShot(1500, then)


def read(label, then):
    try:
        p = panel()
        p._limit_buffers()
        result[label] = shown(p)
        if label == 'moonlightipr':
            p.buffer.showPopup()
            QtCore.QTimer.singleShot(600, lambda: (p.buffer.view().window().grab().save(str(out / 'list.png')), p.buffer.hidePopup()))
    except Exception:
        result[label + ' error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1))
    QtCore.QTimer.singleShot(1500, then)


def finish():
    (out / 'report.json').write_text(json.dumps(result, indent=1))
    QtCore.QTimer.singleShot(1000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('!scene.open {%s} normal' % r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\references\src.lxo')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(8000, lambda: engine('moonlightipr', lambda: read('moonlightipr', lambda: engine('moonray', lambda: read('moonray', finish)))))
