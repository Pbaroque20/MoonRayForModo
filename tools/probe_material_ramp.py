# python
"""Isolated GUI test: a material's ramp opens in the ramp editor from its properties, and a projection's transform
in the graph editor is a move, a turn and a size.

The ramp command of a DwaBaseMaterial's iridescence is run as its button runs it; the dialog is pictured, given a
stop and accepted, and what the material then holds is written down. A planar projection is added to the graph, its
transform's control pictured, opened, changed and accepted, and the matrix the node then holds is written down."""
import json
import pathlib
import re
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/material-ramp'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    from moonray_modo import properties, shader_library
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    held['item'] = modo.Scene().selected[0]
    kinds = [''] + sorted(shader_library.catalog())
    i = kinds.index('DwaBaseMaterial')
    j = sorted(shader_library.catalog()['DwaBaseMaterial']['attributes']).index('iridescence_positions')
    name = 'moonray.material.ramp%d_%d' % (i, j)
    result['command'] = name
    result['in_the_form'] = name in (root / 'kit/MoonRayForModo/material_forms.cfg').read_text(encoding='utf-8')

    def press():
        dialog = QtWidgets.QApplication.activeModalWidget()
        if dialog is None:
            result['dialog'] = 'none'
            return
        result['dialog'] = [type(dialog).__name__, dialog.windowTitle(), dialog.table.rowCount()]
        dialog.add_stop()
        QtWidgets.QApplication.processEvents()
        dialog.grab().save(str(out / 'ramp.png'))
        result['stops_after_adding'] = dialog.table.rowCount()
        dialog.accept()
    QtCore.QTimer.singleShot(800, press)
    lx.eval(name)
    after = properties.read(held['item'])
    result['material_holds'] = {key: value for key, value in after.get('native_parameters', {}).items() if key.startswith('iridescence_')}
    graph = after.get('node_graph')
    if graph:
        result['graph_holds'] = {key: value for key, value in graph['nodes'][graph['root']].get('parameters', {}).items() if key.startswith('iridescence_')}
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        from moonray_modo.node_editor import open_editor
        from moonray_modo.node_widgets import MatrixField
        editor = held['editor'] = open_editor(held['item'])
        centre = editor.view.mapToScene(editor.view.viewport().rect().center())
        before = set(editor.graph['nodes'])
        editor.add_at = QtCore.QPointF(centre.x() - 300, centre.y() + 200)
        editor.selected_input = None
        editor.kinds.setCurrentText('ProjectPlanarMap')
        editor.add(connect=False)
        made = next(iter(set(editor.graph['nodes']) - before))
        editor.canvas.clearSelection()
        editor.items[made].setSelected(True)
        QtWidgets.QApplication.processEvents()
        field = None
        for row in range(editor.table.rowCount()):
            item = editor.table.item(row, 0)
            if (item.data(QtCore.Qt.UserRole) or '') == 'projection_matrix':
                field = editor.table.cellWidget(row, 1)
                editor.table.scrollToItem(item, QtWidgets.QAbstractItemView.PositionAtCenter)
        result['control'] = [type(field).__name__, field.text() if isinstance(field, MatrixField) else None]
        QtWidgets.QApplication.processEvents()
        editor.grab().save(str(out / 'projection.png'))

        def press():
            dialog = QtWidgets.QApplication.activeModalWidget()
            if dialog is None:
                result['matrix_dialog'] = 'none'
                return
            dialog.spins[0][0].setValue(2.0)
            dialog.spins[1][1].setValue(90.0)
            dialog.spins[2][2].setValue(3.0)
            QtWidgets.QApplication.processEvents()
            dialog.grab().save(str(out / 'transform.png'))
            dialog.accept()
        QtCore.QTimer.singleShot(600, press)
        field.open()
        QtWidgets.QApplication.processEvents()
        result['node_holds'] = [round(v, 5) for v in editor.graph['nodes'][made].get('parameters', {}).get('projection_matrix', [])]
        for row in range(editor.table.rowCount()):
            item = editor.table.item(row, 0)
            if (item.data(QtCore.Qt.UserRole) or '') == 'projection_matrix':
                again = editor.table.cellWidget(row, 1)
                result['control_after'] = again.text() if again is not None else None
        editor.grab().save(str(out / 'projection_after.png'))
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(800, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(2500, step2)
