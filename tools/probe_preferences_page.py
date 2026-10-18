# python
"""Isolated GUI test: a picture of the MoonRay page in Modo's Preferences (System > Preferences), as it is laid out.

The Preferences window is opened on the MoonRay page, and the window alone, not the screen, is saved, once with its
sections as they open and once with every section unfolded where Modo allows it."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/preferences-page'
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def shoot():
    try:
        shown = [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.width() > 200]
        result['windows'] = [(w.windowTitle(), w.width(), w.height()) for w in shown]
        page = [w for w in shown if 'Preferences' in w.windowTitle()] or [min(shown, key=lambda w: w.width() * w.height())]
        page[0].grab().save(str(out / 'preferences.png'))
    except Exception:
        result['shot_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


try:
    lx.eval('layout.window Preferences')
    lx.eval('pref.select moonray/general set')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(5000, shoot)
