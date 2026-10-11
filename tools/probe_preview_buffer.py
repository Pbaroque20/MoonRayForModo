# python
"""Isolated GUI test: the preview window's channel buttons, its region drawn by dragging, and its colour probe.

A red block is rendered. The pointer is put over the block and over the empty frame beside it and what the probe says
is written down. Each channel button is pressed and the picture kept. A rectangle is dragged in the picture with the
mouse, as a user drags it, and what the scene then holds as its region is written down."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/preview-buffer'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def mouse(widget, kind, point, button=QtCore.Qt.NoButton, held_buttons=QtCore.Qt.NoButton):
    """Hand a widget a mouse event, as the window system would."""
    event = QtGui.QMouseEvent(kind, QtCore.QPointF(point), button, held_buttons, QtCore.Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(widget, event)


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


try:
    from moonray_modo import materials
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    for key, value in (('cenY', .5), ('sizeX', 1.2), ('sizeY', 1.2), ('sizeZ', 1.2)):
        lx.eval('tool.attr prim.cube %s %s' % (key, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    materials.assign('DwaBaseMaterial', name='Red', color=[.8, .05, .05])
    camera = modo.Scene().renderCamera
    camera.position.set((0.0, .6, 4.0))
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
    QtCore.QTimer.singleShot(25000, look)


def look():
    try:
        panel = panel_widget()
        view = panel.preview
        area = view.image_rect()
        result['image'] = [view.image.width(), view.image.height()]
        # The probe, by the pointer really moving over the picture: the block in the middle, the frame's corner.
        for name, (u, v) in (('on_the_block', (.5, .5)), ('beside_it', (.04, .06))):
            point = QtCore.QPoint(int(area.left() + u * area.width()), int(area.top() + v * area.height()))
            mouse(view, QtCore.QEvent.MouseMove, point)
            QtWidgets.QApplication.processEvents()
            result['probe_' + name] = panel.probe.text()
            result['swatch_' + name] = [panel.swatch.isVisible(), panel.swatch.styleSheet()[:40]]
            panel.window().grab().save(str(out / ('probe_%s.png' % name)))
        view.hovered.emit(-1, -1)
        result['probe_off_the_picture'] = panel.probe.text()
        # Each channel, by its button.
        centre = QtCore.QPoint(int(area.center().x()), int(area.center().y()))
        for key, button in panel.channels.items():
            button.click()
            QtWidgets.QApplication.processEvents()
            shown = view.shown()
            colour = QtGui.QColor(shown.pixel(view.image.width() // 2, view.image.height() // 2))
            result['channel_' + button.text()] = {'buffer': panel.buffer.currentData(), 'viewer': view.channel, 'middle': [colour.red(), colour.green(), colour.blue()],
                                                  'lit': [k for k, other in panel.channels.items() if other.isChecked()], 'status': panel.status.text()[:80]}
            panel.window().grab().save(str(out / ('channel_%s.png' % button.text())))
            if key == 'g':
                # Pressed again, it goes out and the whole picture is back.
                button.click()
                QtWidgets.QApplication.processEvents()
                result['green_pressed_again'] = [view.channel, [k for k, other in panel.channels.items() if other.isChecked()]]
        panel._channel_chosen('rgb')
        # Gamma lifts the picture's middle; its button puts it back.
        before = QtGui.QColor(view.shown().pixel(view.image.width() // 2, view.image.height() // 2)).red()
        panel.gamma.setValue(2.0)
        QtWidgets.QApplication.processEvents()
        lifted = QtGui.QColor(view.shown().pixel(view.image.width() // 2, view.image.height() // 2)).red()
        panel.window().grab().save(str(out / 'gamma_2.png'))
        panel.gamma.setValue(1.0)
        panel.exposure.setValue(1.5)
        result['gamma'] = {'red_at_1': before, 'red_at_2': lifted, 'back_at_1': QtGui.QColor(view.shown().pixel(view.image.width() // 2, view.image.height() // 2)).red()}
        resets = [b for b in panel.findChildren(QtWidgets.QToolButton) if b.text() in ('EV', 'Gamma')]
        next(b for b in resets if b.text() == 'EV').click()
        result['exposure_after_reset'] = panel.exposure.value()
        result['buffers'] = [panel.buffer.itemText(i) for i in range(panel.buffer.count())]
        # The region: switched on, then dragged with the left button.
        panel.region_enabled.setChecked(True)
        QtWidgets.QApplication.processEvents()
        result['tool_on'] = view.region_tool
        a = QtCore.QPoint(int(area.left() + .3 * area.width()), int(area.top() + .25 * area.height()))
        b = QtCore.QPoint(int(area.left() + .7 * area.width()), int(area.top() + .8 * area.height()))
        mouse(view, QtCore.QEvent.MouseButtonPress, a, QtCore.Qt.LeftButton, QtCore.Qt.LeftButton)
        mouse(view, QtCore.QEvent.MouseMove, QtCore.QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2), QtCore.Qt.NoButton, QtCore.Qt.LeftButton)
        mouse(view, QtCore.QEvent.MouseMove, b, QtCore.Qt.NoButton, QtCore.Qt.LeftButton)
        QtWidgets.QApplication.processEvents()
        view.grab().save(str(out / 'region_dragging.png'))
        mouse(view, QtCore.QEvent.MouseButtonRelease, b, QtCore.Qt.LeftButton)
        QtWidgets.QApplication.processEvents()
        from moonray_modo import properties, scene_settings
        stored = scene_settings.complete(properties.scene_settings())
        result['region_stored'] = [stored['region_enabled'], stored['region']]
        result['region_shown'] = view.region
        result['status'] = panel.status.text()
        result['form_agrees'] = [lx.eval('moonray.render.region_left ?'), lx.eval('moonray.render.region_bottom ?')]
        # The block is moved aside: only inside the region may the picture follow it.
        result['fitted_to_region'] = [round(view.zoom, 3), round(view.pan.x(), 1), round(view.pan.y(), 1)]
    except Exception:
        result['look_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(12000, finish)


def finish():
    try:
        panel = panel_widget()
        panel.window().grab().save(str(out / 'window.png'))
        result['after_region'] = [panel.status.text(), panel.image_info.text()]
        # Switched off, the view is the whole frame's again.
        panel.region_enabled.click()
        QtWidgets.QApplication.processEvents()
        result['region_off'] = [panel.region_enabled.isChecked(), panel.preview.zoom, panel.preview.region]
        # And on again, it does not come back as it was drawn before.
        panel.region_enabled.click()
        QtWidgets.QApplication.processEvents()
        from moonray_modo import properties, scene_settings
        again = scene_settings.complete(properties.scene_settings())
        result['region_on_again'] = [panel.preview.region, panel.preview.region_tool, again['region_enabled'], again['region'], panel.preview.zoom]
        panel.region_enabled.click()
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        panel.preferences.store.setValue('runtime', held['stored'])
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(5000, start)
