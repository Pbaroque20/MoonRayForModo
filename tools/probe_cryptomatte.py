# python
"""Isolated GUI test: render two cubes with a Cryptomatte output and picture its preview."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/cryptomatte'
out.mkdir(parents=True, exist_ok=True)
result = {}
import faulthandler
_fault = open(str(out / 'fault.log'), 'w')
faulthandler.enable(_fault, all_threads=True)


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


def step2():
    try:
        panel = panel_widget()
        result['engine'] = panel.preview_engine.currentData()
        result['was_ipr'] = panel.ipr_mode.isChecked()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        panel.ipr_mode.setChecked(True)
        result['idle_with_ipr'] = [panel.start.text(), panel._following]
        import shiboken2
        result['valid'] = {n: shiboken2.isValid(getattr(panel, n)) for n in ('options_menu', 'clay_menu', 'options_button', 'show_buckets', 'worker_tiles', 'preview_lock', 'clay_group')}
        result['valid']['clay_actions'] = [shiboken2.isValid(a) for a in panel.clay_group.actions()]
        result['valid']['menu_actions'] = [a.text() for a in panel.options_menu.actions()] if shiboken2.isValid(panel.options_menu) else None
        try:
            panel._follow(True)
            panel._follow(False)
        except Exception:
            result['follow_error'] = traceback.format_exc()
        panel.start.click()
        result['started'] = [panel.start.text(), panel._following, panel.timer.isActive()]
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(14000, step3)


def step3():
    try:
        panel = panel_widget()
        result['before_edit'] = [panel.renderer.generation, panel.status.text(), panel.start.text()]
        panel.window().grab().save(str(out / 'ipr-before.png'))
        import modo
        camera = modo.Scene().renderCamera
        before = camera.channel('focusDist').get()
        rect = panel.preview.image_rect()
        panel.focus_at(QtCore.QPoint(int(rect.left() + rect.width() * 0.25), int(rect.top() + rect.height() * 0.8)))
        result['focus'] = [before, camera.channel('focusDist').get(), panel.status.text()]
        panel.focus_at(QtCore.QPoint(int(rect.center().x()), int(rect.top() + 4)))
        result['focus_miss'] = panel.status.text()
        result['camera_z'] = camera.channel('pos.Z').get()
        lx.eval('select.itemType mesh')
        lx.eval('transform.channel pos.Y 0.6')
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(9000, step4)


def step4():
    try:
        panel = panel_widget()
        result['after_edit'] = [panel.renderer.generation, panel.status.text(), panel.start.text()]
        panel.window().grab().save(str(out / 'ipr-after.png'))
        panel.start.click()
        result['stopped'] = [panel.start.text(), panel._following, panel.ipr_mode.isChecked(), panel.timer.isActive()]
        panel.ipr_mode.setChecked(False)
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        panel.buffer.setCurrentIndex(panel.buffer.findData('crypto_material'))
        result['chosen'] = [panel.status.text(), properties_now()]
    except Exception:
        result['step4_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(24000, step5)


def step5():
    try:
        panel = panel_widget()
        result['crypto'] = [panel.status.text(), panel.buffer.currentText(), panel.start.text()]
        panel.window().grab().save(str(out / 'crypto-ids.png'))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(result['engine']))
        panel.ipr_mode.setChecked(result['was_ipr'])
    except Exception:
        result['step5_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(8000, step2)
