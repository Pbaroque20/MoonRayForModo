# python
"""Isolated GUI test: the preview window before anything is rendered shows MoonRay's crest."""
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/crest'
out.mkdir(parents=True, exist_ok=True)
try:
    lx.eval('moonray.open')
except Exception:
    (out / 'error.txt').write_text(traceback.format_exc())


def look():
    try:
        from moonray_modo import crest
        from moonray_modo.panel import Panel
        panel = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
        panel.window().resize(900, 620)
        QtWidgets.QApplication.processEvents()
        panel.window().grab().save(str(out / 'empty.png'))
        (out / 'report.txt').write_text('shape: %s, image null: %s' % (crest.shape() is not None, panel.preview.image.isNull()))
    except Exception:
        (out / 'error.txt').write_text(traceback.format_exc())
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(15000, look)
