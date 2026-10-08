# python
"""Isolated GUI test: open the material graph editor on a small graph and picture it."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/graph-editor'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


try:
    from moonray_modo import properties
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('vertMap.new {Second UV} txuv')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    held['item'] = modo.Scene().selected[0]
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        from moonray_modo.node_editor import open_editor
        editor = held['editor'] = open_editor(held['item'])
        result['modal'] = editor.isModal()
        root_id = editor.graph['root']
        known = [editor.kinds.itemText(i) for i in range(editor.kinds.count())]
        # An image feeding the albedo, as dragging a wire off the input to empty canvas does.
        centre = editor.view.mapToScene(editor.view.viewport().rect().center())
        for key, kind, dx, dy in (('albedo', 'ImageMap', -320, -80), ('roughness', 'NoiseMap', -320, 120)):
            if kind not in known:
                continue
            editor.add_at = QtCore.QPointF(centre.x() + dx, centre.y() + dy)
            editor.selected_input = (root_id, key)
            editor.kinds.setCurrentText(kind)
            editor.add(connect=True)
        editor.canvas.clearSelection()
        editor.frame(everything=True)
        result['nodes'] = {key: [value['type'], value.get('inputs')] for key, value in editor.graph['nodes'].items()}
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2500, step3)


def step3():
    try:
        editor = held['editor']
        editor.grab().save(str(out / 'editor.png'))
        root_id = editor.graph['root']
        editor.items[root_id].setSelected(True)
        editor.toggle_expanded(root_id)
        editor.frame(everything=True)
        QtWidgets.QApplication.processEvents()
        editor.grab().save(str(out / 'editor-expanded.png'))
        editor.toggle_expanded(root_id)
        fields = {}
        for row in range(editor.table.rowCount()):
            widget = editor.table.cellWidget(row, 1)
            fields[editor.table.item(row, 0).text()] = type(widget).__name__ if widget is not None else None
        result['field_kinds'] = sorted(set(str(v) for v in fields.values()))
        for row in range(editor.table.rowCount()):
            name = editor.table.item(row, 0).data(QtCore.Qt.UserRole)
            widget = editor.table.cellWidget(row, 1)
            if name == 'casts_caustics':
                widget.setCurrentIndex(1); widget.activated.emit(1)
            elif name == 'specular_model':
                widget.setCurrentIndex(0); widget.activated.emit(0)
        for row in range(editor.table.rowCount()):
            name = editor.table.item(row, 0).data(QtCore.Qt.UserRole)
            widget = editor.table.cellWidget(row, 1)
            if name == 'metallic_color':
                widget.spins[0].setValue(0.25)
            elif name == 'roughness':
                editor.describe_row(row)
        result['help'] = editor.property_help.text()
        result['color'] = editor.graph['nodes'][root_id].get('parameters', {}).get('metallic_color')
        result['set'] = {key: editor.graph['nodes'][root_id].get('parameters', {}).get(key) for key in ('casts_caustics', 'specular_model')}
        result['selected_before_events'] = editor.selected()
        QtWidgets.QApplication.processEvents()
        result['selected_after_events'] = [editor.selected(), editor.table.rowCount(), editor.table.isVisible()]
        editor.grab().save(str(out / 'editor-properties.png'))
        editor.canvas.clearSelection()
        if 'image' in [editor.kinds.itemText(i) for i in range(editor.kinds.count())]:
            editor.kinds.setCurrentText('image')
            editor.add()
            image_id = editor.selected()
            for row in range(editor.table.rowCount()):
                if editor.table.item(row, 0).data(QtCore.Qt.UserRole) == 'uv_map':
                    widget = editor.table.cellWidget(row, 1)
                    result['uv_widget'] = type(widget).__name__
                    result['uv_entries'] = [widget.itemText(i) for i in range(widget.count())]
                    if widget.count() > 1:
                        widget.setCurrentIndex(1); widget.activated.emit(1)
            result['uv_set'] = editor.graph['nodes'][image_id].get('parameters', {}).get('uv_map')
            QtWidgets.QApplication.processEvents()
            editor.grab().save(str(out / 'editor-uv.png'))
            editor.remove()
        editor.kinds.setCurrentText('RampMap'); editor.add()
        made = editor.selected()
        result['new_ramp_space'] = editor.graph['nodes'][made]['parameters'].get('space')
        rows = {}
        for row in range(editor.table.rowCount()):
            if not editor.table.isRowHidden(row):
                rows[editor.table.item(row, 0).text()] = type(editor.table.cellWidget(row, 1)).__name__
        result['ramp_rows'] = {k: v for k, v in rows.items() if 'ramp' in k or k in ('colors', 'positions', 'interpolations')}
        editor.set_ramp(made, 'positions', [0.0, 0.5, 1.0], [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [1, 1, 1])
        editor.set_value(made, 'uv_repeat', -1, [3.0, 2.0])
        editor.set_value(made, 'input', -1, 0.25)
        # No value may be left written in a cell that a control stands over.
        result['text_under_controls'] = [editor.table.item(row, 0).text() for row in range(editor.table.rowCount())
                                         if editor.table.cellWidget(row, 1) is not None and editor.table.item(row, 1) is not None and editor.table.item(row, 1).text()]
        ramp_now = editor.graph['nodes'][made]['parameters']
        result['ramp_set'] = [ramp_now.get('positions'), ramp_now.get('colors'), ramp_now.get('interpolations'), editor.info.text()]
        result['ramp_selected_after'] = editor.selected() == made
        for row in range(editor.table.rowCount()):
            if isinstance(editor.table.cellWidget(row, 1), QtWidgets.QPushButton):
                editor.table.scrollToItem(editor.table.item(row, 0), QtWidgets.QAbstractItemView.PositionAtTop)
        QtWidgets.QApplication.processEvents()
        editor.grab().save(str(out / 'ramp-field.png'))
        from moonray_modo.ramp_editor import RampDialog
        dialog = RampDialog('test', [0.0, 1.0], [[1, 0, 0], [0, 0, 1]], [1, 1], True, editor)
        dialog.show(); dialog.grab().save(str(out / 'ramp-dialog.png')); dialog.close()
        editor.set_value(made, 'space', -1, 0)
        editor.rebuild()
        result['camera_message'] = editor.info.text()
        for row in range(editor.table.rowCount()):
            if editor.table.item(row, 0).data(QtCore.Qt.UserRole) == 'space':
                widget = editor.table.cellWidget(row, 1)
                result['space_choices'] = [widget.itemText(i) for i in range(widget.count())]
        editor.frame(everything=True)
        QtWidgets.QApplication.processEvents()
        editor.grab().save(str(out / 'editor-ramp.png'))
        editor.fix_camera_ramps()
        result['after_fix'] = [editor.graph['nodes'][made]['parameters'].get('space'), editor.info.text()]
        editor.canvas.clearSelection(); editor.items[made].setSelected(True); editor.remove()
        editor.canvas.clearSelection()
        other = next(key for key in editor.items if key != root_id)
        editor.items[other].setSelected(True)
        editor.duplicate()
        result['after_duplicate'] = len(editor.graph['nodes'])
        editor.remove()
        result['after_delete'] = len(editor.graph['nodes'])
        editor.undo(); editor.undo()
        result['after_undo'] = len(editor.graph['nodes'])
        editor.quick_add()
        QtWidgets.QApplication.processEvents()
        editor.popup.search.setText('noi')
        QtWidgets.QApplication.processEvents()
        result['quick'] = [editor.popup.results.item(i).text() for i in range(min(4, editor.popup.results.count()))]
        editor.popup.grab().save(str(out / 'quick-add.png'))
        editor.popup.close()
        editor.frame(everything=True)
        editor.save(False)
        result['materials'] = [editor.material_picker.itemText(i) for i in range(editor.material_picker.count())]
        from moonray_modo import properties
        stored = properties.read(held['item'])
        result['saved'] = [stored.get('native_shader'), len((stored.get('node_graph') or {}).get('nodes', {})), editor.info.text()]
        editor.grab().save(str(out / 'editor-final.png'))
        editor.reject()
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(7000, step2)
