# python
"""Isolated GUI test: open the preview window and the Render item's MoonRay form, and picture both."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/preview-window'
out.mkdir(parents=True, exist_ok=True)
result = {}


def shot(name):
    for index, window in enumerate(w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.width() > 300):
        window.grab().save(str(out / ('%s-%d.png' % (name, index))))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.open')
    lx.eval('moonray.page settings')
    result['samples'] = lx.eval('moonray.render.samples ?')
    lx.eval('moonray.render.samples 6')
    lx.eval('moonray.render.exposure 1.5')
    lx.eval('moonray.render.aov_depth true')
    lx.eval('moonray.render.background_color {0.2 0.4 0.6}')
    from moonray_modo import properties
    result['stored'] = properties.scene_settings()
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        from moonray_modo.panel import Panel
        panel = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
        result['panel'] = [panel.width(), panel.height(), panel.exposure.value(), panel.start.text()]
        shot('open')
        panel.render_once()
        result['after_submit'] = panel.status.text()
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(14000, step3)


def step3():
    try:
        from moonray_modo.panel import Panel
        panel = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
        result['done'] = [panel.status.text(), panel.image_info.text(), panel.render_timing.text(), panel.start.text(), panel.notice_toggle.text()]
        panel.window().grab().save(str(out / 'panel.png'))
        from moonray_modo.preferences import Dialog
        dialog = Dialog(panel.preferences, panel)
        dialog.show()
        dialog.grab().save(str(out / 'preferences.png'))
        dialog.close()
        menu = panel._options_menu()
        menu.show()
        menu.grab().save(str(out / 'options.png'))
        menu.close()
        panel._image_menu()
        panel.exposure.setValue(0.5)
        panel._commit_exposure()
        panel.region_enabled.setChecked(True)
        result['written'] = [panel._settings_values()['display']['exposure'], panel._settings_values()['region_enabled']]
        lx.eval('moonray.page stop')
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(8000, step2)
