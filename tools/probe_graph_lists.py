# python
"""Isolated GUI test: how the graph editor shows the properties that are lists of numbers or a matrix.

For every kind of node the editor offers, its property list is built and each property that MoonRay holds as a list,
a ramp or a matrix is written down with the control it is given. Pictures are taken of a material's iridescence
rows and of a projection node's matrix."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/graph-lists'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}
PICTURES = [name for name in os.environ.get('PROBE_PICTURES', 'DwaBaseMaterial:iridescence,ProjectPlanarMap:projection_matrix,DwaToonMaterial:toon_specular,HairToonMaterial:specular_1').split(',') if name]


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    from moonray_modo import properties
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    held['item'] = modo.Scene().selected[0]
except Exception:
    result['error'] = traceback.format_exc()
save()


def rows(editor):
    found = []
    for row in range(editor.table.rowCount()):
        item = editor.table.item(row, 0)
        widget = editor.table.cellWidget(row, 1)
        cell = editor.table.item(row, 1)
        found.append((item.data(QtCore.Qt.UserRole) or item.text(), item.text(), editor.table.isRowHidden(row), type(widget).__name__ if widget is not None else None, cell.text() if cell is not None else ''))
    return found


def step2():
    try:
        from moonray_modo import nodes
        from moonray_modo.node_editor import open_editor
        editor = held['editor'] = open_editor(held['item'])
        known = [editor.kinds.itemText(i) for i in range(editor.kinds.count())]
        centre = editor.view.mapToScene(editor.view.viewport().rect().center())
        listed = {}
        for kind in known:
            try:
                schema = nodes.specs(kind)
            except Exception:
                continue
            wanted = {key for key, spec in schema.items() if 'Vector' in spec['type'] or spec['type'].startswith('Mat') or spec['type'] in ('Vec4f',)}
            if not wanted:
                continue
            before = set(editor.graph['nodes'])
            editor.add_at = QtCore.QPointF(centre.x() - 300, centre.y() + 200)
            editor.selected_input = None
            editor.kinds.setCurrentText(kind)
            editor.add(connect=False)
            made = next(iter(set(editor.graph['nodes']) - before), None)
            if made is None:
                continue
            editor.canvas.clearSelection()
            editor.items[made].setSelected(True)
            QtWidgets.QApplication.processEvents()
            shown = rows(editor)
            listed[kind] = {key: [label, hidden, widget, text[:60]] for key, label, hidden, widget, text in shown if key in wanted}
            for picture in PICTURES:
                name, word = picture.split(':')
                if name == kind:
                    for row in range(editor.table.rowCount()):
                        item = editor.table.item(row, 0)
                        if word in (item.data(QtCore.Qt.UserRole) or '') and not editor.table.isRowHidden(row):
                            editor.table.scrollToItem(item, QtWidgets.QAbstractItemView.PositionAtTop)
                            break
                    QtWidgets.QApplication.processEvents()
                    editor.grab().save(str(out / (kind + '.png')))
        result['listed'] = listed
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(800, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(2500, step2)
