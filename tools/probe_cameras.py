# python
"""Isolated GUI test: choose a MoonRay fisheye camera in the preview window and render through it."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/cameras'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


try:
    for x in (-1.2, 0.0, 1.2):
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.cube on')
        for name, value in (('cenX', x), ('cenY', 0.5), ('cenZ', 0), ('sizeX', 0.8), ('sizeY', 1.0), ('sizeZ', 0.8)):
            lx.eval('tool.attr prim.cube %s %s' % (name, value))
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
    scene = modo.Scene()
    camera = scene.renderCamera
    for kind in ('FisheyeCamera', 'SphericalCamera'):
        item = scene.addItem('moonray.' + kind, name=kind)
        # Where the Modo camera is, looking the same way.
        lx.eval('select.item {%s} set' % item.id)
        for channel in ('pos.X', 'pos.Y', 'pos.Z', 'rot.X', 'rot.Y', 'rot.Z'):
            pass
        held[kind] = item
    from moonray_modo import camera_choice
    result['choices'] = camera_choice.choices()
    result['query_before'] = lx.eval('moonray.camera ?')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        panel = panel_widget()
        held['engine'] = panel.preview_engine.currentData()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        result['combo'] = [panel.camera.itemText(i) for i in range(panel.camera.count())]
        # Put the fisheye where the Modo camera is.
        from moonray_modo import host
        camera = modo.Scene().renderCamera
        fisheye = held['FisheyeCamera']
        lx.eval('select.item {%s} set' % fisheye.id)
        for axis, value in zip('XYZ', camera.position.get()):
            lx.eval('transform.channel pos.%s %s' % (axis, value))
        index = next(i for i in range(panel.camera.count()) if panel.camera.itemData(i) == fisheye.id)
        panel.camera.setCurrentIndex(index)
        panel.camera.activated.emit(index)
        from moonray_modo import camera_choice
        result['after_choice'] = [camera_choice.current() == fisheye.id, lx.eval('moonray.camera ?'), panel.status.text()]
        panel.start.click()
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(20000, step3)


def step3():
    try:
        panel = panel_widget()
        result['fisheye'] = [panel.status.text(), panel.notice_toggle.text(), panel.warnings.toPlainText()[:400]]
        panel.window().grab().save(str(out / 'fisheye.png'))
        panel.camera.setCurrentIndex(0)
        panel.camera.activated.emit(0)
        from moonray_modo import camera_choice
        result['back_to_modo'] = [camera_choice.current(), lx.eval('moonray.camera ?')]
        panel.start.click()
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(15000, step4)


def step4():
    try:
        panel = panel_widget()
        result['modo'] = panel.status.text()
        panel.window().grab().save(str(out / 'modo-camera.png'))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
    except Exception:
        result['step4_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(8000, step2)
