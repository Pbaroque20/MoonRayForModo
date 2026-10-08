# python
"""Isolated GUI test: assign a MoonShine material, edit its albedo, and record what the form shows."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/material-form'
out.mkdir(parents=True, exist_ok=True)
result = {}


def shot(name):
    for index, window in enumerate(w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.width() > 300):
        window.grab().save(str(out / ('%s-%d.png' % (name, index))))


try:
    from moonray_modo import shader_library, properties
    scene = modo.Scene()
    lx.eval('item.create mesh')
    lx.eval('script.run "macro.scriptservice:32235710027:macro"') if False else None
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    mesh = scene.selectedByType('mesh')[0]
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    material = scene.selected[0]
    result['layers'] = [(i.name, i.type) for i in scene.renderItem.children()]
    names = [''] + sorted(shader_library.catalog())
    i = names.index('DwaBaseMaterial')
    keys = sorted(shader_library.catalog()['DwaBaseMaterial']['attributes'])
    command = 'moonray.material.attr%d_%d' % (i, keys.index('albedo'))
    result['command'] = command
    result['before'] = str(lx.eval(command + ' ?'))
    lx.eval(command + ' {0.8 0.2 0.1}')
    result['after'] = str(lx.eval(command + ' ?'))
    result['stored'] = properties.read(material).get('native_parameters')
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def step2():
    try:
        shot('selected')
        lx.eval(command + ' {0.1 0.9 0.1}')
        lx.eval('moonray.material.attr%d_%d 0.123' % (i, keys.index('roughness')))
        from moonray_modo import property_notifications
        result['clients'] = len(property_notifications.Notifier.clients)
    except Exception:
        result['shot_error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(2500, step3)


def step3():
    try:
        shot('edited')
    except Exception:
        result['shot_error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))
    QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(7000, step2)
