# python
"""GUI: MoonRay LS's Resolution in Preview Preferences, a share of the render's. A 1180 x 2000 portrait camera; the
dialog's choices and the size the preview window says LS renders at for each share (realtime at a third), with the
dialog pictured. Preferences put back as they were. Writes test-results/ls-fraction/report.json."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/ls-fraction'
out.mkdir(parents=True, exist_ok=True)
result = {'planned': {}}
KEYS = ('ipr/fraction', 'preview_fraction', 'preview_engine', 'xpu2/renderer')


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def run():
    panel = None
    held = {}
    try:
        from moonray_modo.panel import live_panels
        from moonray_modo.preferences import Dialog
        panel = live_panels()[0]
        held = {key: panel.preferences.store.value(key) for key in KEYS}
        render = modo.Scene().renderItem
        lx.eval('item.channel polyRender$resX 1180 item:{%s}' % render.id)
        lx.eval('item.channel polyRender$resY 2000 item:{%s}' % render.id)
        panel.preferences.set('preview_fraction', 3)
        dialog = Dialog(panel.preferences, panel)
        dialog.show()
        QtWidgets.QApplication.processEvents()
        widget = dialog.widgets['ipr/fraction']
        result['choices'] = [(widget.itemText(i), widget.itemData(i)) for i in range(widget.count())]
        result['shown'] = widget.currentText()
        result['old_row_gone'] = 'ipr/width' not in dialog.widgets
        widget.setCurrentIndex(widget.findData(8))
        dialog.grab().save(str(out / 'preferences.png'))
        dialog.accept()
        result['stored_after_ok'] = panel.preferences.get('ipr/fraction')
        # MoonRay LS is offered with the standard XPU only.
        panel.preferences.set('xpu2/renderer', 'xpu')
        panel._sync_engines()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray_ls'))
        result['engine'] = panel.preview_engine.currentData()
        for share in (1, 2, 4, 8, 16):
            panel.preferences.set('ipr/fraction', share)
            panel._show_planned()
            QtWidgets.QApplication.processEvents()
            result['planned'][share] = panel.image_info.text()
    except Exception:
        result['error'] = traceback.format_exc()
    finally:
        if panel is not None:
            for key, value in held.items():
                if value is None:
                    panel.preferences.store.remove(key)
                else:
                    panel.preferences.store.setValue(key, value)
    save()
    QtCore.QTimer.singleShot(1000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('scene.new')
    lx.eval('moonray.open')
except Exception:
    result['open_error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, run)
