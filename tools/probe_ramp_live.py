# python
"""Isolated GUI test: a toon material's ramp edited with the mouse, shown at once, and kept or dropped.

A ball with a DwaToonMaterial, in MoonLightIPR with realtime on. The diffuse ramp's editor is opened from the material's
form. Its last stop (white, at 1) is dragged with the mouse to a tenth of the way along: the ball in the preview
brightens while the editor is still open. Cancel: the ball is as it was and nothing was stored. The same again with
OK: the ramp is stored."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/ramp-live'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def ball():
    """How bright the middle of the picture is, where the ball is."""
    image = panel_widget().preview.image.convertToFormat(QtGui.QImage.Format_RGB888)
    if image.isNull():
        return None
    total = count = 0
    for y in range(image.height() // 3, 2 * image.height() // 3, 3):
        for x in range(image.width() // 3, 2 * image.width() // 3, 3):
            colour = image.pixelColor(x, y)
            total += colour.red() + colour.green() + colour.blue()
            count += 3
    return round(total / float(count), 2)


def note(name, **more):
    from moonray_modo import properties
    stored = properties.read(held['item']).get('native_parameters', {})
    result['steps'].append(dict({'step': name, 'ball': ball(), 'positions_read': stored.get('positions'), 'live': dict(properties.LIVE),
                                 'status': panel_widget().status.text()[:60]}, **more))
    panel_widget().preview.grab().save(str(out / ('%d_%s.png' % (len(result['steps']), name))))
    save()


def send(widget, kind, point, button, buttons):
    QtWidgets.QApplication.sendEvent(widget, QtGui.QMouseEvent(kind, QtCore.QPointF(point), button, buttons, QtCore.Qt.NoModifier))


def drag_last_stop(then):
    """With the editor open: drag the stop at 1 to a tenth of the way along, wait, say what the preview shows, then
    press OK or Cancel."""
    def act():
        try:
            dialog = QtWidgets.QApplication.activeModalWidget()
            preview = dialog.preview
            positions = dialog.lists()[0]
            row = max(range(len(positions)), key=lambda i: positions[i])
            start = preview.handle(row).toPoint()
            end = QtCore.QPoint(int(preview.across(0.1)), start.y())
            send(preview, QtCore.QEvent.MouseButtonPress, start, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
            for step in range(1, 11):
                send(preview, QtCore.QEvent.MouseMove, start + (end - start) * step / 10.0, QtCore.Qt.NoButton, QtCore.Qt.LeftButton)
            send(preview, QtCore.QEvent.MouseButtonRelease, end, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
            held['dragged'] = dialog.result()[0]
            dialog.grab().save(str(out / ('editor_%s.png' % then)))
        except Exception:
            result.setdefault('errors', []).append(['drag', traceback.format_exc()])
            save()

    def finish():
        try:
            note('editor_open_after_drag_' + then, dragged_positions=held.get('dragged'))
            dialog = QtWidgets.QApplication.activeModalWidget()
            dialog.accept() if then == 'ok' else dialog.reject()
        except Exception:
            result.setdefault('errors', []).append(['finish', traceback.format_exc()])
            save()
    QtCore.QTimer.singleShot(1500, act)
    QtCore.QTimer.singleShot(6000, finish)
    lx.eval('!select.drop item')
    lx.eval('!select.subItem {%s} set textureLayer' % held['item'].id)
    lx.eval('moonray.material.ramp13_81')


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(9000)
def begin():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
    panel.start.click()


@step(4000)
def cancelled():
    note('before')
    drag_last_stop('cancel')


@step(4000)
def kept():
    note('after_cancel')
    drag_last_stop('ok')


@step(500)
def finish_():
    note('after_ok')
    panel_widget().stop()


def run(index=0):
    if index >= len(STEPS):
        save()
        lx.eval('!!app.quit')
        return
    function, wait = STEPS[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append([function.__name__, traceback.format_exc()])
        save()
    QtCore.QTimer.singleShot(wait, lambda: run(index + 1))


try:
    from moonray_modo import materials, properties
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    scene = modo.Scene()
    mesh = scene.selected[0]
    with mesh.geometry as g:
        for index in range(len(g.polygons)):
            g.polygons[index].materialTag = 'toon'
    mask = scene.addItem('mask', name='Toon mask')
    mask.setParent(scene.renderItem, materials.above_base(scene, mask))
    mask.channel('ptyp').set('Material')
    mask.channel('ptag').set('toon')
    held['item'] = scene.addItem(properties.LAYER_PREFIX + 'DwaToonMaterial', name='DwaToonMaterial')
    held['item'].setParent(mask, 0)
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
