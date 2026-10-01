# python
"""Reload installed CPU translation modules without changing the open scene."""
import importlib
from PySide2 import QtWidgets
from moonray_modo import textures, layers, graph, moonshine, rdla, host, panel
for module in (textures, layers, graph, moonshine, rdla, host):
    importlib.reload(module)
app = QtWidgets.QApplication.instance()
if app:
    for widget in app.allWidgets():
        if isinstance(widget, panel.Panel) and not widget.disposed:
            widget.render_once()
print('Installed CPU translation updates loaded; open scene preserved.')
