# python
"""Isolated GUI test of the look-dev fixes: an input wired in the graph editor is greyed in Properties and its value
cannot be set there (the wire stays); a material node's inputs in folding groups; and a graph edit told to the live
preview as a material's edit, not as a new scene. Writes test-results/lookdev-fixes/report.json and pictures."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/lookdev-fixes'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def command_for(shader, key):
    from moonray_modo import shader_library
    types = [''] + sorted(shader_library.catalog())
    keys = sorted(shader_library.catalog()[shader]['attributes'])
    return 'moonray.material.attr%d_%d' % (types.index(shader), keys.index(key))


try:
    from moonray_modo import properties
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    held['item'] = modo.Scene().selected[0]
    result['item'] = [held['item'].name, held['item'].type]
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        from moonray_modo.node_editor import open_editor
        from moonray_modo.changes import Changes
        editor = held['editor'] = open_editor(held['item'])
        held['changes'] = Changes();held['changes'].consume()
        root_id = editor.graph['root']
        centre = editor.view.mapToScene(editor.view.viewport().rect().center())
        editor.add_at = QtCore.QPointF(centre.x() - 320, centre.y())
        editor.selected_input = (root_id, 'roughness')
        editor.kinds.setCurrentText('NoiseMap')
        editor.add(connect=True)
        editor.canvas.clearSelection();editor.frame(everything=True)
        result['wired'] = editor.graph['nodes'][root_id].get('inputs')
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1500, step3)


def step3():
    try:
        from moonray_modo import material_override, properties
        item = held['item']
        full, items = held['changes'].consume()
        result['graph_write_told_as'] = {'full': full, 'material_in_items': item.id in items}
        result['stored_inputs'] = properties.read(item)['node_graph']['nodes'][properties.read(item)['node_graph']['root']].get('inputs')
        result['driver'] = material_override.driver(item, 'roughness')
        name = command_for('DwaBaseMaterial', 'roughness')
        result['command'] = name
        lx.eval('select.item {%s} set' % item.id)
        try:
            lx.eval('%s 0.3' % name);result['set_while_wired'] = 'accepted'
        except Exception as exc:
            result['set_while_wired'] = 'refused: ' + str(exc)
        after = properties.read(item)['node_graph']
        result['wire_after_set'] = after['nodes'][after['root']].get('inputs')
        other = command_for('DwaBaseMaterial', 'metallic')
        try:
            lx.eval('%s 0.5' % other);result['set_unwired'] = 'accepted'
        except Exception as exc:
            result['set_unwired'] = 'refused: ' + str(exc)
        held['editor'].grab().save(str(out / 'grouped.png'))
        node = held['editor'].items[held['editor'].graph['root']]
        result['node_height_grouped'] = node.rect().height()
        result['sockets_grouped'] = sorted(k for k in node.sockets if k)
        held['editor'].fold_port_group('DwaBaseMaterial', 'Specular')
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1200, step4)


def step4():
    try:
        editor = held['editor']
        editor.frame(everything=True);QtWidgets.QApplication.processEvents()
        editor.grab().save(str(out / 'specular-toggled.png'))
        node = editor.items[editor.graph['root']]
        result['node_height_toggled'] = node.rect().height()
        result['sockets_toggled'] = sorted(k for k in node.sockets if k)
        editor.fold_port_group('DwaBaseMaterial', 'Specular')
    except Exception:
        result['step4_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(800, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(4000, step2)
