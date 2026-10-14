# python
"""Isolated GUI test: the About window, pictured and closed."""
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/about'
out.mkdir(parents=True, exist_ok=True)


def picture():
    try:
        dialog = QtWidgets.QApplication.activeModalWidget()
        dialog.grab().save(str(out / 'about.png'))
        (out / 'size.txt').write_text('%d x %d' % (dialog.width(), dialog.height()))
        dialog.accept()
    except Exception:
        (out / 'error.txt').write_text(traceback.format_exc())
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!!app.quit'))


QtCore.QTimer.singleShot(3000, lambda: (QtCore.QTimer.singleShot(2500, picture), lx.eval('moonray.about')))
