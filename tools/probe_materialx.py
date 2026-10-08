# python
"""Isolated GUI test: import a MaterialX file onto a ball, render it in the preview window and open its graph.

The file is PROBE_MTLX."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/materialx'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


try:
    from moonray_modo import properties
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    for name, value in (('cenX', 0), ('cenY', 0.5), ('cenZ', 0), ('sizeX', 0.5), ('sizeY', 0.5), ('sizeZ', 0.5)):
        lx.eval('tool.attr prim.sphere %s %s' % (name, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    scene = modo.Scene()
    mesh = scene.selected[0]
    result['uv_maps'] = [vmap.name for vmap in mesh.geometry.vmaps.uvMaps]
    before = {item.id for item in scene.items('advancedMaterial')}
    lx.eval('moonray.material.importMaterialX {%s}' % os.environ.get('PROBE_MTLX', ''))
    made = [item for item in scene.items('advancedMaterial') if item.id not in before]
    result['made'] = [item.name for item in made]
    settings = properties.read(made[0])
    held['material'] = made[0]
    graph = settings.get('node_graph') or {}
    result['graph'] = {'nodes': len(graph.get('nodes', {})), 'root': graph.get('nodes', {}).get(graph.get('root'), {}).get('type'),
                       'native_shader': settings.get('native_shader'), 'source': graph.get('materialx_source')}
    result['tags'] = sorted({polygon.materialTag for polygon in mesh.geometry.polygons})
    # A file the importer cannot follow must say so and leave the scene alone.
    bad = out / 'unsupported.mtlx'
    bad.write_text('<materialx version="1.38"><nonesuch name="n" type="surfaceshader"/><surfacematerial name="m" type="material">'
                   '<input name="surfaceshader" type="surfaceshader" nodename="n"/></surfacematerial></materialx>')
    count = len(scene.items('advancedMaterial'))
    scene.select(mesh)
    try:
        lx.eval('!moonray.material.importMaterialX {%s}' % bad)
        result['unsupported'] = 'no error raised'
    except Exception as exc:
        result['unsupported'] = str(exc)[:120]
    result['materials_after_unsupported'] = len(scene.items('advancedMaterial')) - count
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        panel = panel_widget()
        held['engine'] = panel.preview_engine.currentData()
        held['ipr'] = panel.preferences.store.value('ipr', '')
        held['runtime'] = panel.preferences.store.value('runtime', '')
        panel.preferences.set('runtime', str(root / 'runtime' / os.environ.get('PROBE_RUNTIME', 'steady-0349-candidate')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        panel.start.click()
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(40000, step3)


def step3():
    try:
        panel = panel_widget()
        result['preview'] = [panel.status.text(), panel.warnings.toPlainText()[:600]]
        panel.window().grab().save(str(out / 'preview.png'))
        if panel._rendering:
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        # The window's choices are shared with the user's own Modo: put back what was stored.
        for key in ('runtime', 'ipr'):
            if held[key]:
                panel.preferences.store.setValue(key, held[key])
            else:
                panel.preferences.store.remove(key)
        from moonray_modo.node_editor import open_editor
        editor = open_editor(held['material'])
        held['editor'] = editor
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(3000, step4)


def step4():
    try:
        editor = held['editor']
        editor.frame(True)
        QtWidgets.QApplication.processEvents()
        editor.grab().save(str(out / 'editor.png'))
        result['editor'] = [len(editor.graph['nodes']), editor.info.text()]
        editor.close()
    except Exception:
        result['step4_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(8000, step2)
