# python
"""Isolated GUI test (tools/launch_gui_probe.py, a test profile): the preview window's top row at several widths, as
Modo draws it. Each width's row is kept as a picture in MOONRAY_PROBE_OUT, and report.json says, for each button and
list, the room it was given beside what its words need (a word cut short shows as needing more than it has)."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ['MOONRAY_PROBE_OUT'])
out.mkdir(parents=True, exist_ok=True)
WIDTHS = [int(v) for v in os.environ.get('MOONRAY_PROBE_WIDTHS', '1400,1000,800,640,520').split(',')]
result = {'widths': {}}


def panel():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def needs(widget):
    """What a widget's words need, as its own style draws it (its size hint), beside what it has."""
    text = widget.currentText() if isinstance(widget, QtWidgets.QComboBox) else getattr(widget, 'text', lambda: '')()
    return {'text': text, 'has': widget.width(), 'needs': widget.sizeHint().width(), 'visible': widget.isVisible()}


def measure(index=0):
    try:
        view = panel()
        window = view.window()
        if index >= len(WIDTHS):
            (out / 'report.json').write_text(json.dumps(result, indent=1), encoding='utf-8')
            lx.eval('!app.quit')
            return
        width = WIDTHS[index]
        window.resize(width, max(window.height(), 600))
        view.resize(width, view.height())
        QtWidgets.QApplication.processEvents()

        def grab():
            try:
                # The whole of the top row, however many lines it takes: what holds the groups of buttons.
                bar = view.start.parentWidget()
                while bar.parentWidget() is not None and bar.parentWidget() is not view and bar.parentWidget().height() < 200:
                    bar = bar.parentWidget()
                bar.grab().save(str(out / ('row_%d.png' % width)))
                widgets = [w for w in bar.findChildren(QtWidgets.QWidget) if w.isVisible()
                           and isinstance(w, (QtWidgets.QAbstractButton, QtWidgets.QComboBox, QtWidgets.QDoubleSpinBox))]
                result['widths'][width] = {'panel': view.width(), 'bar': [bar.width(), bar.height()], 'widgets': [needs(w) for w in widgets]}
            except Exception:
                result['widths'][width] = {'error': traceback.format_exc()}
            QtCore.QTimer.singleShot(200, lambda: measure(index + 1))
        QtCore.QTimer.singleShot(700, grab)
    except Exception:
        result['error'] = traceback.format_exc()
        (out / 'report.json').write_text(json.dumps(result, indent=1), encoding='utf-8')
        lx.eval('!app.quit')


try:
    lx.eval('moonray.open')
except Exception:
    result['error_open'] = traceback.format_exc()
QtCore.QTimer.singleShot(6000, measure)
