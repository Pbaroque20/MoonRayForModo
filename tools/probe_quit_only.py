# python
"""Does a test Modo that does nothing quit cleanly?"""
import lx
from PySide2 import QtCore
QtCore.QTimer.singleShot(4000, lambda: lx.eval("!app.quit"))
