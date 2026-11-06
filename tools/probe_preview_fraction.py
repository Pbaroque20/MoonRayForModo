# python
"""GUI: Preview Preferences' Realtime preview resolution. In the test Modo, a width once chosen in pixels (960) is
stored and the window opened: what the row shows; 1/4 chosen and the window accepted: what is stored; then the
preview's size for a tall scene (1180 x 2000) and a wide one (1920 x 1080) with realtime on, and for a render. Writes
test-results/preview-fraction/report.json and a picture of the window."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\preview-fraction')
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def check():
    try:
        from moonray_modo import preferences
        from moonray_modo.panel import live_panels
        held = preferences.Preferences()
        held.store.remove('preview_fraction')
        held.store.setValue('preview_size', 960)
        result['read before'] = held.get('preview_fraction')
        dialog = preferences.Dialog(held)
        dialog.show()
        QtWidgets.QApplication.processEvents()
        box = dialog.widgets['preview_fraction']
        label = dialog.findChildren(QtWidgets.QFormLayout)[0].labelForField(box)
        result['row'] = [label.text() if label else None, box.currentText(), [box.itemText(i) for i in range(box.count())], box.toolTip()]
        dialog.grab().save(str(out / 'dialog.png'))
        box.setCurrentIndex(box.findData(4))
        dialog.accept()
        result['stored after'] = [held.store.value('preview_fraction'), preferences.Preferences().get('preview_fraction')]
        panel = live_panels()[0]
        panel.ipr_mode.setChecked(True)
        result['rt capable'] = panel._rt_capable()
        result['sizes'] = {name: [panel._dimensions({'width': w, 'height': h}), panel._dimensions({'width': w, 'height': h}, final=True)]
                           for name, (w, h) in (('tall', (1180, 2000)), ('wide', (1920, 1080)))}
        panel.ipr_mode.setChecked(False)
        held.store.remove('preview_fraction')
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


try:
    lx.eval('moonray.open')
except Exception:
    result['open'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(6000, check)
