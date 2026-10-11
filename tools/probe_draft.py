# python
"""Isolated GUI test: the preview window's draft mode, and a region rendered on it.

A block, a dense ball and a ground are made. Draft is switched on with the preview following the scene: the picture is
then lines on paper and nothing is rendered. A region is dragged and, when it has rendered, the picture is kept: lines
outside the region, the render inside. Draft is switched off again."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/draft'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def mouse(widget, kind, point, button=QtCore.Qt.NoButton, held_buttons=QtCore.Qt.NoButton):
    QtWidgets.QApplication.sendEvent(widget, QtGui.QMouseEvent(kind, QtCore.QPointF(point), button, held_buttons, QtCore.Qt.NoModifier))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def colour(view, u, v):
    c = QtGui.QColor(view.image.pixel(int(u * view.image.width()), int(v * view.image.height())))
    return [c.red(), c.green(), c.blue()]


try:
    from moonray_modo import materials
    for tool, values in (('prim.cube', dict(cenY=-.05, sizeX=8, sizeY=.1, sizeZ=8)), ('prim.cube', dict(cenX=-1.0, cenY=.6, sizeX=1.2, sizeY=1.2, sizeZ=1.2)),
                         ('prim.sphere', dict(cenX=1.0, cenY=.7, sizeX=.7, sizeY=.7, sizeZ=.7, sides=96, segments=64))):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set %s on' % tool)
        for key, value in values.items():
            lx.eval('tool.attr %s %s %s' % (tool, key, value))
        lx.eval('tool.apply')
        lx.eval('tool.set %s off' % tool)
    materials.assign('DwaBaseMaterial', name='Red', color=[.8, .05, .05])
    camera = modo.Scene().renderCamera
    camera.position.set((0.0, 1.6, 6.0))
    camera.rotation.set((-.15, 0.0, 0.0))
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def start():
    try:
        panel = panel_widget()
        held['stored'] = panel.preferences.store.value('runtime', '')
        held['engine'] = panel.preview_engine.currentData()
        panel.preferences.set('runtime', str(root / 'runtime/steady-0350-pool'))
        panel.window().resize(1000, 700)
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
        QtWidgets.QApplication.processEvents()
        if panel.start.text() == 'Render':
            panel.start.click()
    except Exception:
        result['start_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(20000, draft_on)


def draft_on():
    try:
        panel = panel_widget()
        result['rendered_middle'] = colour(panel.preview, .5, .9)
        panel.draft.click()
    except Exception:
        result['draft_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(6000, region)


def region():
    try:
        import time
        from moonray_modo import draft
        panel = panel_widget()
        view = panel.preview
        result['draft'] = {'status': panel.status.text(), 'info': panel.image_info.text(), 'corner': colour(view, .02, .03), 'foot': colour(view, .02, .97),
                           'button': panel.start.text(), 'engine_running': panel._rendering}
        began = time.perf_counter()
        scene = panel._capture()
        found = draft.segments(scene, 640, 360)
        result['lines'] = {'count': len(found), 'seconds': round(time.perf_counter() - began, 3),
                           'per_mesh': [[m['name'], len(m['faces']), len(draft.lines(m)[1])] for m in scene['meshes']]}
        panel.window().grab().save(str(out / 'draft.png'))
        panel.region_enabled.click()
        QtWidgets.QApplication.processEvents()
        area = view.image_rect()
        a = QtCore.QPoint(int(area.left() + .2 * area.width()), int(area.top() + .3 * area.height()))
        b = QtCore.QPoint(int(area.left() + .55 * area.width()), int(area.top() + .85 * area.height()))
        mouse(view, QtCore.QEvent.MouseButtonPress, a, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        mouse(view, QtCore.QEvent.MouseMove, b, QtCore.Qt.NoButton, QtCore.Qt.LeftButton)
        mouse(view, QtCore.QEvent.MouseButtonRelease, b, QtCore.Qt.LeftButton)
    except Exception:
        result['region_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(15000, look)


def look():
    try:
        panel = panel_widget()
        view = panel.preview
        result['with_region'] = {'status': panel.status.text(), 'info': panel.image_info.text(), 'zoom': view.zoom, 'outside': colour(view, .02, .03),
                                 'inside': colour(view, .3, .8), 'region': view.region}
        panel.window().grab().save(str(out / 'draft_region.png'))
        panel.region_enabled.click()
        panel.draft.click()
    except Exception:
        result['look_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(12000, finish)


def finish():
    try:
        panel = panel_widget()
        result['draft_off'] = {'status': panel.status.text(), 'info': panel.image_info.text(), 'corner': colour(panel.preview, .02, .03)}
        panel.window().grab().save(str(out / 'draft_off.png'))
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        panel.preferences.store.setValue('runtime', held['stored'])
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(5000, start)
