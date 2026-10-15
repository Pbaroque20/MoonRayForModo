# python
"""Isolated GUI test: the Outputs window with a visibility output for every light, one for a light group and a
primitive attribute output. The window is pictured, what it says of the expressions written down, and what it keeps
once accepted."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/outputs-window'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def show():
    try:
        from moonray_modo import outputs
        from moonray_modo.outputs_dialog import OutputsDialog
        dialog = held['dialog'] = OutputsDialog([], None)
        dialog.add({'name': 'visibility', 'kind': 'visibility', 'expression': outputs.visibility_expression('')})
        dialog.add({'name': 'key_visibility', 'kind': 'visibility', 'expression': outputs.visibility_expression('key')})
        dialog.add({'name': 'heat', 'kind': 'attribute', 'expression': 'Heat'})
        dialog.show()
        result['types'] = [dialog.table.cellWidget(row, 1).currentText() for row in range(dialog.table.rowCount())]
        result['problem'] = dialog.problem.text()
    except Exception:
        result['error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(1500, finish)


def finish():
    try:
        dialog = held['dialog']
        dialog.grab().save(str(out / 'outputs_window.png'))
        dialog.accept()
        result['kept'] = [(v['name'], v['kind'], v['expression']) for v in dialog.entries]
    except Exception:
        result['error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(4000, show)
