# python
"""Isolated GUI test: an edit in the graph editor reaches the preview while IPR follows the scene."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/live-graph'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


try:
    from moonray_modo import properties
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    held['item'] = modo.Scene().selected[0]
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        panel = panel_widget()
        held['engine'], held['ipr'] = panel.preview_engine.currentData(), panel.ipr_mode.isChecked()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        panel.ipr_mode.setChecked(True)
        panel.start.click()
        from moonray_modo.node_editor import open_editor
        held['editor'] = open_editor(held['item'])
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(14000, step3)


def step3():
    try:
        panel, editor = panel_widget(), held['editor']
        result['before'] = [panel.renderer.generation, panel.status.text()]
        panel.window().grab().save(str(out / 'before.png'))
        editor.set_value(editor.graph['root'], 'albedo', -1, [0.9, 0.1, 0.1])
        result['scene_has_edit'] = properties_now().get('native_parameters')
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(9000, step4)


def properties_now():
    from moonray_modo import properties
    return properties.read(held['item'])


def step4():
    try:
        panel, editor = panel_widget(), held['editor']
        result['after_edit'] = [panel.renderer.generation, panel.status.text()]
        panel.window().grab().save(str(out / 'after-edit.png'))
        editor.reject()
    except Exception:
        result['step4_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(9000, step5)


def step5():
    try:
        panel = panel_widget()
        result['after_close'] = [panel.renderer.generation, panel.status.text()]
        panel.window().grab().save(str(out / 'after-close.png'))
        panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        panel.ipr_mode.setChecked(held['ipr'])
    except Exception:
        result['step5_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(8000, step2)
