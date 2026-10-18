# python
"""Isolated GUI test: MoonRay LS's Sampling choice in the preview's Preferences window. The window is made, pictured,
switched to Uniform (Adaptive error should grey) and pictured again, then closed without saving."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\ls-sampling')
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def check():
    try:
        from moonray_modo.preferences import Preferences, Dialog
        dialog = Dialog(Preferences())
        dialog.show()
        sampling = dialog.widgets['ipr/sampling']
        result['choices'] = [sampling.itemText(i) for i in range(sampling.count())]
        result['adaptive'] = {'chosen': sampling.currentData(), 'error_enabled': dialog.error.isEnabled()}
        dialog.grab().save(str(out / 'adaptive.png'))
        sampling.setCurrentIndex(sampling.findData('uniform'))
        result['uniform'] = {'chosen': sampling.currentData(), 'error_enabled': dialog.error.isEnabled()}
        dialog.grab().save(str(out / 'uniform.png'))
        dialog.reject()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(4000, check)
