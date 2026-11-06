# python
"""Isolated GUI test: the pictures of the user guide, taken from a small scene set up for them.

A ground, a gold ball and a red block in MoonRay materials, a MoonRay rect light and a VDB cloud. Pictures are taken
of Modo's window with a material, a MoonRay item and the render settings in its Properties, of the preview window
drawing the scene with MoonLightIPR and with MoonRay, of the graph editor and of the light path expressions editor.
PROBE_VDB names the cloud's file. The pictures go to docs/images/guide."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'docs/images/guide'
out.mkdir(parents=True, exist_ok=True)
report = root / 'test-results/user-guide'
report.mkdir(parents=True, exist_ok=True)
result = {'pictures': []}
held = {}


def save():
    (report / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def main_window():
    return max((w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()), key=lambda w: w.width() * w.height())


def picture(name, widget=None):
    QtWidgets.QApplication.processEvents()
    (widget or main_window()).grab().save(str(out / (name + '.png')))
    result['pictures'].append(name)


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def shape(tool, name, **values):
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('tool.set %s on' % tool)
    for key, value in values.items():
        lx.eval('tool.attr %s %s %s' % (tool, key, value))
    lx.eval('tool.apply')
    lx.eval('tool.set %s off' % tool)
    mesh = modo.Scene().selected[0]
    mesh.name = name
    return mesh


try:
    from moonray_modo import entities, materials, properties
    scene = modo.Scene()
    shape('prim.cube', 'Ground', cenX=0, cenY=-.05, cenZ=0, sizeX=30, sizeY=.1, sizeZ=30)
    ball = shape('prim.sphere', 'Ball', cenX=-1.3, cenY=.8, cenZ=0, sizeX=.8, sizeY=.8, sizeZ=.8)
    scene.select(ball)
    held['gold'] = materials.assign('DwaMetalMaterial', name='Gold', color=[1.0, .77, .34])
    block = shape('prim.cube', 'Block', cenX=1.3, cenY=.65, cenZ=.3, sizeX=1.3, sizeY=1.3, sizeZ=1.3)
    scene.select(block)
    held['paint'] = materials.assign('DwaBaseMaterial', name='Red Paint', color=[.75, .08, .06])
    light = scene.addItem(entities.item_type('RectLight'), name='Key Light')
    light.position.set((-1.5, 4.0, 3.0))
    light.rotation.set((-50.0, -25.0, 0.0), degrees=True)
    for key, value in (('intensity', 120.0), ('width', 3.0), ('height', 2.0)):
        light.channel(entities.CHANNEL_PREFIX + key).set(value)
    held['light'] = light
    cloud_file = os.environ.get('PROBE_VDB', '')
    if cloud_file:
        fog = scene.addItem(entities.item_type('VdbVolume'), name='Cloud Fog')
        cloud = scene.addItem(entities.item_type('VdbGeometry'), name='Cloud')
        cloud.channel(entities.CHANNEL_PREFIX + 'model').set(cloud_file)
        cloud.channel(entities.CHANNEL_PREFIX + 'modo_volume').set('Cloud Fog')
        cloud.position.set((.3, 3.2, -3.5))
        held['cloud'] = cloud
    camera = scene.renderCamera
    camera.position.set((.6, 2.0, 7.5))
    camera.rotation.set((-6.0, 3.0, 0.0), degrees=True)
    scene.select(held['paint'])
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        picture('material-properties')
        modo.Scene().select(held['light'])
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2500, step3)


def step3():
    try:
        picture('moonray-item')
        modo.Scene().select(modo.Scene().renderItem)
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2500, step4)


def step4():
    try:
        picture('render-settings')
        # The MoonRay menu, where the menu bar will give it up.
        try:
            bar = main_window().findChild(QtWidgets.QMenuBar)
            action = next(a for a in bar.actions() if a.text().replace('&', '') == 'MoonRay')
            menu = action.menu()
            menu.popup(bar.mapToGlobal(bar.actionGeometry(action).bottomLeft()))
            QtWidgets.QApplication.processEvents()
            picture('moonray-menu', menu)
            menu.close()
        except Exception as exc:
            result['menu'] = str(exc)
        lx.eval('moonray.open')
    except Exception:
        result['step4_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(4000, step5)


def step5():
    try:
        panel = panel_widget()
        held['engine'] = panel.preview_engine.currentData()
        held['stored'] = {key: panel.preferences.store.value(key, '') for key in ('runtime', 'ipr')}
        panel.preferences.set('runtime', str(root / 'runtime/steady-0350-pool'))
        panel.window().resize(1000, 720)
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
        QtWidgets.QApplication.processEvents()
        if panel.start.text() == 'Render':
            panel.start.click()
    except Exception:
        result['step5_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(30000, step6)


def step6():
    try:
        panel = panel_widget()
        result['moonlightipr'] = [panel.status.text(), panel.warnings.toPlainText()[:600]]
        picture('preview-moonlightipr', panel.window())
        picture('modo-with-preview')
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        if panel.start.text() == 'Render':
            panel.start.click()
    except Exception:
        result['step6_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(120000, step7)


def step7():
    try:
        panel = panel_widget()
        result['moonray'] = [panel.status.text(), panel.warnings.toPlainText()[:600]]
        picture('preview-moonray', panel.window())
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        # The window's choices are shared with the user's own Modo: put back what was stored.
        for key, value in held['stored'].items():
            panel.preferences.store.setValue(key, value)
        from moonray_modo.node_editor import open_editor
        editor = held['editor'] = open_editor(held['paint'])
        editor.resize(1280, 760)
    except Exception:
        result['step7_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(3000, step8)


def step8():
    try:
        picture('graph-editor', held['editor'])
        held['editor'].close()
        from moonray_modo.outputs_dialog import OutputsDialog
        dialog = held['dialog'] = OutputsDialog([{'name': 'key_light', 'kind': 'lpe', 'expression': "C.*<L.'key'>"},
                                                 {'name': 'reflections', 'kind': 'lpe', 'expression': 'C<RS>.*[<L.>O]'}], main_window())
        dialog.show()
        QtWidgets.QApplication.processEvents()
        picture('light-path-expressions', dialog)
        dialog.close()
    except Exception:
        result['step8_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(3500, step2)
