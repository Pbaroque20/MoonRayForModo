# python
"""Runs only in the isolated graphical Modo test profile."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

result = {'headless': lx.service.Platform().IsHeadless()}
destination = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\gui-probe.json')
try:
    result['command_registered'] = lx.service.Command().Spawn(0, 'moonray.open').test()
    lx.eval('moonray.open')
    result['command_executed'] = True
except Exception:
    result['error'] = traceback.format_exc()

def inspect_panel():
    try:
        from moonray_modo.panel import Panel
        panels = [widget for widget in QtWidgets.QApplication.allWidgets() if isinstance(widget, Panel)]
        result['panels'] = [{'visible': panel.isVisible(), 'width': panel.width(), 'height': panel.height()} for panel in panels]
    except Exception:
        result['panel_error'] = traceback.format_exc()
    destination.write_text(json.dumps(result, indent=2), encoding='utf-8')

QtCore.QTimer.singleShot(3000, inspect_panel)
destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
