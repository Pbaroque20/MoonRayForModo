# python
"""Isolated GUI test: the light path expressions editor adds a preset as a row, and marks an expression written wrong.

Every preset is chosen from the menu, the first one twice, so its second name has to differ. Then one expression is
broken and mended, and what the editor says each time is written down with a picture of it."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/light-paths'
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def run():
    try:
        from moonray_modo import outputs
        from moonray_modo.outputs_dialog import OutputsDialog
        dialog = OutputsDialog([{'name': 'key_light', 'kind': 'lpe', 'expression': "C.*<L.'key'>"}])
        dialog.show()
        button = next(b for b in dialog.findChildren(QtWidgets.QPushButton) if b.text() == 'Add light path preset')
        actions = button.menu().actions()
        for action in actions + actions[:1]:
            action.trigger()
        table = dialog.table
        result['rows'] = [[table.item(row, 0).text(), table.cellWidget(row, 1).currentData(), table.item(row, 2).text()] for row in range(table.rowCount())]
        result['clean'] = dialog.problem.text()
        table.item(1, 2).setText('C<RD[<L.>O]')
        QtWidgets.QApplication.processEvents()
        result['broken'] = [dialog.problem.text(), table.item(1, 2).toolTip()]
        dialog.grab().save(str(out / 'broken.png'))
        table.item(1, 2).setText('C<RD>[<L.>O]')
        QtWidgets.QApplication.processEvents()
        result['mended'] = dialog.problem.text()
        result['values'] = len(outputs.values(result['rows'] and [{'name': n, 'kind': k, 'expression': e} for n, k, e in result['rows']]))
        dialog.grab().save(str(out / 'mended.png'))
        dialog.close()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(3000, run)
