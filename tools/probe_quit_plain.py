# python
"""Modo with no kit of ours: does showing a bare Python Qt window, closing it, and quitting crash Modo? The exit code is
the answer (1 a clean scripted quit, 3221225477 a crash). PROBE_QUIT_PLAIN=none quits without the window."""
import os
import lx
from PySide2 import QtCore, QtWidgets

kept = []


def window():
    if os.environ.get('PROBE_QUIT_PLAIN') == 'none':
        return
    shown = QtWidgets.QWidget()
    shown.setWindowTitle('probe')
    shown.resize(300, 200)
    shown.show(); shown.raise_(); shown.activateWindow()
    kept.append(shown)
    QtCore.QTimer.singleShot(1500, shown.close)


QtCore.QTimer.singleShot(1500, window)
QtCore.QTimer.singleShot(5000, lambda: lx.eval('!app.quit'))
