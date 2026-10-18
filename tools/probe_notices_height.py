# python
"""Isolated GUI test: the preview's notices open only as tall as their text and two lines more.

The preview window is opened and its notices shown with: none, one short notice, three, and forty. For each the
notices' height in pixels is noted and the preview window pictured (test-results/notices/<n>.png)."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/notices'
out.mkdir(parents=True, exist_ok=True)
result = {}
CASES = [('none', []), ('one', ['Material Glass: a reflection amount apart from the specular amount is not followed.']),
         ('three', ['Material Glass: a reflection amount apart from the specular amount is not followed.',
                    'Anisotropy requires MoonShine Material: Brushed', 'MoonLightIPR leaves out the fur of Rug.']),
         ('forty', ['Notice number %d about something the renderer could not carry over.' % i for i in range(40)])]


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def show(name, messages):
    def step():
        panel = panel_widget()
        panel._set_notices(messages)
        panel.notice_toggle.setChecked(True)
        QtWidgets.QApplication.processEvents()

        def picture():
            QtWidgets.QApplication.processEvents()
            result[name] = {'height': panel.warnings.height(), 'line': panel.warnings.fontMetrics().lineSpacing(),
                            'lines': panel.warnings.document().size().height()}
            panel.window().grab().save(str(out / (name + '.png')))
        QtCore.QTimer.singleShot(800, picture)
    return step


def run(steps, index=0):
    if index >= len(steps):
        try:
            panel_widget().notice_toggle.setChecked(False)
        except Exception:
            pass
        (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
        lx.eval('!app.quit')
        return
    try:
        steps[index]()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    QtCore.QTimer.singleShot(1500, lambda: run(steps, index + 1))


try:
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(5000, lambda: run([show(name, messages) for name, messages in CASES]))
