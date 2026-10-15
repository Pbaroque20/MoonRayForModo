# python
"""Isolated GUI test: a MoonShine material's properties in the graph editor, in groups that fold away.

The graph editor is opened on a DwaBaseMaterial and its surface node selected. The group headers are written down and
the panel pictured; the Specular group is folded by clicking its header, and pictured; the filter is set to a word
inside the folded group, and the rows it shows written down; the editor is closed and opened again to see that the
fold was kept."""
import json
import traceback
from pathlib import Path
import lx
import modo
from PySide2 import QtCore, QtWidgets

ROOT = Path('C:/Users/Raphael Tobar/MoonRayForModo')
out = ROOT / 'test-results/graph-groups'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def editor():
    from moonray_modo.node_editor import Editor
    return next(w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, Editor) and w.isVisible())


def visible(e):
    return [(e.table.item(r, 0).text(), r in e.group_rows) for r in range(e.table.rowCount()) if not e.table.isRowHidden(r)]


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def step1():
    try:
        e = editor()
        e.items['surface'].setSelected(True)
        QtWidgets.QApplication.processEvents()
        result['headers'] = list(e.group_rows.values())
        result['first_rows'] = visible(e)[:8]
        e.grab().save(str(out / '1_open.png'))
        row = next(r for r, g in e.group_rows.items() if g == 'Specular')
        e.table.cellClicked.emit(row, 0)
        QtWidgets.QApplication.processEvents()
        names = [n for n, header in visible(e)]
        result['specular_folded'] = {'header_shows': e.table.item(row, 0).text(),
                                     'its_rows_shown': sum(1 for r, g in e.row_groups.items() if g == 'Specular' and r < e.table.rowCount() and not e.table.isRowHidden(r))}
        e.table.scrollToItem(e.table.item(row, 0))
        e.grab().save(str(out / '2_folded.png'))
        e.property_search.setText('roughness')
        QtWidgets.QApplication.processEvents()
        result['searched'] = visible(e)
        e.property_search.setText('')
        e.close()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1500, reopen)


def reopen():
    try:
        lx.eval('moonray.material.nodes')
        QtCore.QTimer.singleShot(2500, step2)
    except Exception:
        result['error2'] = traceback.format_exc(); save(); lx.eval('!app.quit')


def step2():
    try:
        e = editor()
        e.items['surface'].setSelected(True)
        QtWidgets.QApplication.processEvents()
        row = next(r for r, g in e.group_rows.items() if g == 'Specular')
        result['kept_after_reopening'] = e.table.item(row, 0).text()
        # Leave it as it was.
        e.table.cellClicked.emit(row, 0)
        e.close()
    except Exception:
        result['error2'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


try:
    from moonray_modo import nodes, properties
    item = modo.Scene().addMaterial(name='Grouped')
    properties.write(item, {'node_graph': nodes.new(), 'node_override': True})
    modo.Scene().select(item)
    lx.eval('moonray.material.nodes')
    QtCore.QTimer.singleShot(3000, step1)
except Exception:
    result['error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')
