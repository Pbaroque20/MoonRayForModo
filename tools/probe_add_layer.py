# python
"""Isolated GUI test: what the Shader Tree's Add Layer does with a native MoonRay material entry."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/add-layer'
out.mkdir(parents=True, exist_ok=True)
result = {}


def layers():
    scene = modo.Scene()
    found = []
    for item in scene.renderItem.children():
        found.append([item.name, item.type, [[child.name, child.type] for child in item.children()]])
    return found


try:
    from moonray_modo import properties
    result['before'] = layers()
    service = lx.service.Scene()
    for name in ('material.moonrayMoonShine', 'material.dw.DwaBaseMaterial'):
        try:
            result['type ' + name] = service.ItemTypeLookup(name)
        except Exception:
            result['type ' + name] = 'unknown type'
    lx.eval('select.item {%s} set' % modo.Scene().renderItem.id)
    made = modo.Scene().addItem('material.dw.DwaBaseMaterial')
    made.setParent(modo.Scene().renderItem, 1)
    result['made'] = [made.name, made.type]
    for name in ('material.moonrayMoonShine', 'material.dw.DwaBaseMaterial'):
        try:
            lx.eval('shader.create %s' % name)
            result['create ' + name] = 'created'
        except Exception:
            result['create ' + name] = traceback.format_exc()[-200:]
    result['after'] = layers()
    result['selected'] = [[item.name, item.type, properties.read(item).get('native_shader')] for item in modo.Scene().selected]
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def shot():
    try:
        from moonray_modo import properties
        result['later'] = layers()
        scene = modo.Scene()
        made = [item for item in scene.items('advancedMaterial', superType=True) if item.type.startswith('material.dw.')]
        result['made_later'] = [[item.name, item.type, properties.read(item).get('native_shader'), bool(item.PackageTest('moonray.shader.DwaBaseMaterial'))] for item in made]
        if made:
            lx.eval('select.item {%s} set' % made[0].id)
            from moonray_modo import shader_library, host
            names = [''] + sorted(shader_library.catalog())
            keys = sorted(shader_library.catalog()['DwaBaseMaterial']['attributes'])
            command = 'moonray.material.attr%d_%d' % (names.index('DwaBaseMaterial'), keys.index('albedo'))
            lx.eval(command + ' {0.2 0.6 0.9}')
            result['albedo'] = properties.read(made[0]).get('native_parameters')
            result['graph_command_enabled'] = bool(lx.eval('query commandservice command.enable ? moonray.material.nodes')) if False else None
        for index, window in enumerate(w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.width() > 300):
            window.grab().save(str(out / ('window-%d.png' % index)))
    except Exception:
        result['shot_error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))
    QtCore.QTimer.singleShot(2500, final)


def final():
    try:
        for index, window in enumerate(w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.width() > 300):
            window.grab().save(str(out / ('selected-%d.png' % index)))
    except Exception:
        result['final_error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))
    QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(3000, shot)
