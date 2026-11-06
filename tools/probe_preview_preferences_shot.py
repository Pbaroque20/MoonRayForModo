# python
"""GUI: a picture of the preview window's Preview Preferences, for the docs. Opens the preview, shows the dialog without
waiting on it, grabs it and closes it (nothing saved). Writes test-results/preview-preferences/dialog.png."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\preview-preferences')
out.mkdir(parents=True, exist_ok=True)
result = {}


def shoot():
    try:
        from moonray_modo.panel import live_panels
        from moonray_modo.preferences import Dialog
        p = live_panels()[0]
        dialog = Dialog(p.preferences, p)
        dialog.show()
        dialog.adjustSize()
        for _ in range(10):
            QtWidgets.QApplication.processEvents()
        dialog.grab().save(str(out / 'dialog.png'))
        result['size'] = [dialog.width(), dialog.height()]
        dialog.reject()
    except Exception:
        result['error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1))
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


try:
    lx.eval('moonray.open')
except Exception:
    result['open_error'] = traceback.format_exc()
QtCore.QTimer.singleShot(6000, shoot)
