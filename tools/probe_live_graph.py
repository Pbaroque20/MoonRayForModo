# python
"""Isolated GUI test: the material form, the graph editor and the preview stay in step.

An image chosen for an input in the form appears as a node in the open graph editor and in
the preview; an edit in the editor is written to the material and shows in the form.
"""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/live-graph'
out.mkdir(parents=True, exist_ok=True)
image = root / 'kit/MoonRayForModo/assets/about-moonray.png'
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def stored():
    from moonray_modo import properties
    return properties.read(held['item'])


def commands():
    from moonray_modo import shader_library
    names = [''] + sorted(shader_library.catalog())
    keys = sorted(shader_library.catalog()['DwaBaseMaterial']['attributes'])
    index = names.index('DwaBaseMaterial')
    return {key: ('moonray.material.attr%d_%d' % (index, keys.index(key)), 'moonray.material.map%d_%d' % (index, keys.index(key))) for key in ('albedo', 'roughness')}


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
        result['image_before'] = lx.eval(commands()['albedo'][1] + ' ?')
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(14000, step3)


def step3():
    try:
        panel, editor = panel_widget(), held['editor']
        result['before'] = [panel.renderer.generation, len(editor.graph['nodes'])]
        # What choosing Load Image in the form does, without its file dialog.
        from moonray_modo import properties, graph_images, material_override
        settings = stored()
        graph = graph_images.set_image(settings, 'albedo', str(image))
        lx.eval('moonray.material.applyGraph {%s} %s' % (held['item'].id, properties.encode(material_override.synchronize(settings, graph))))
        lx.eval('select.item {%s} set' % held['item'].id)
        result['form_shows_image'] = lx.eval(commands()['albedo'][1] + ' ?')
        result['editor_after_form'] = sorted(node['type'] for node in editor.graph['nodes'].values())
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(10000, step4)


def step4():
    try:
        panel, editor = panel_widget(), held['editor']
        result['after_image'] = [panel.renderer.generation, panel.status.text(), panel.notice_toggle.text()]
        panel.window().grab().save(str(out / 'after-image.png'))
        editor.grab().save(str(out / 'editor-after-image.png'))
        # An edit in the editor: no Apply.
        editor.set_value(editor.graph['root'], 'roughness', -1, 0.15)
        result['scene_after_editor'] = stored().get('native_parameters')
        result['form_after_editor'] = lx.eval(commands()['roughness'][0] + ' ?')
        # Moving a node is not an edit to the material.
        generation = panel.renderer.generation
        other = next(key for key in editor.items if key != editor.graph['root'])
        editor.items[other].setPos(editor.items[other].pos() + QtCore.QPointF(40, 40))
        editor.remember(None)
        held['generation_before_move'] = generation
        # The form removes the image.
        lx.eval(commands()['albedo'][1] + ' 0')
        result['editor_after_clear'] = sorted(node['type'] for node in editor.graph['nodes'].values())
    except Exception:
        result['step4_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(9000, step5)


def step5():
    try:
        panel, editor = panel_widget(), held['editor']
        result['after_clear'] = [panel.renderer.generation, panel.status.text()]
        panel.window().grab().save(str(out / 'after-clear.png'))
        editor.reject()
        panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        panel.ipr_mode.setChecked(held['ipr'])
    except Exception:
        result['step5_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(8000, step2)
