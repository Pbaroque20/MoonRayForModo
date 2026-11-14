# python
"""GUI test: the ocean scene's graph (PROBE_SCENE, his testOcean), a Mix node with Ocean Foam wired to its Mix selected;
pictures the editor and reports the colour the Mix number is drawn in (greyed out while connected)."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/graph-grey'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    held['item'] = next(i for i in modo.Scene().items('advancedMaterial') if 'DwaBaseMaterial' in i.name and '(2)' in i.name)
except Exception:
    result['error'] = traceback.format_exc()
save()


def colours(widget):
    found = {'widget': type(widget).__name__,
             'text': widget.palette().color(QtGui.QPalette.Text).name(),
             'sheet': widget.styleSheet()}
    edit = widget.findChild(QtWidgets.QLineEdit)
    if edit is not None:
        found['line_text'] = edit.palette().color(QtGui.QPalette.Text).name()
        found['line_sheet'] = edit.styleSheet()
    found['app_sheet'] = QtWidgets.QApplication.instance().styleSheet()[:2000]
    return found


def step2():
    try:
        from moonray_modo.node_editor import open_editor
        editor = held['editor'] = open_editor(held['item'])
        mix = next(k for k, v in editor.graph['nodes'].items() if v['type'] == 'mix' and 'mix' in (v.get('inputs') or {}))
        editor.canvas.clearSelection()
        editor.items[mix].setSelected(True)
        QtWidgets.QApplication.processEvents()
        editor.inspect()
        QtWidgets.QApplication.processEvents()
        rows = {}
        for row in range(editor.table.rowCount()):
            name = editor.table.item(row, 0).data(QtCore.Qt.UserRole)
            widget = editor.table.cellWidget(row, 1)
            if widget is not None:
                rows[name] = colours(widget)
        result['rows'] = rows
        result['selected'] = editor.selected()
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, step3)


def step3():
    try:
        held['editor'].grab().save(str(out / 'editor.png'))
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    try:
        held['editor'].close()
    except Exception:
        pass
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(3000, step2)
