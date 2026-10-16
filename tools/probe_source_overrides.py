# python
"""Isolated GUI test: the MoonRay page of Modo's Preferences, with its MoonRay Source Overrides section.

The page's form is shown on its own (attr.formPopover) and pictured; the three overrides are read through their
commands."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/source-overrides'
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def shoot():
    try:
        shown = [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()]
        result['windows'] = [(w.windowTitle(), w.width(), w.height()) for w in shown]
        for i, window in enumerate(sorted(shown, key=lambda w: w.width() * w.height())[:3]):
            window.grab().save(str(out / ('window_%d.png' % i)))
    except Exception:
        result['shot_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


try:
    result['values'] = {name: lx.eval('moonray.pref.%s ?' % name) for name in ('toonTerminator', 'toonAlbedo', 'lightMotion')}
    lx.eval('attr.formPopover {MoonRayPreferences:sheet}')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(4000, shoot)
