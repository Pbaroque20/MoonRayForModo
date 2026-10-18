# python
"""Isolated GUI test: Modo's File menu with the kit's Export as MoonRay Scene in it. The menu's sheet is shown on its
own (attr.formPopover) and pictured whole: Modo's own entries should all be there, Export as MoonRay Scene at the end."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\file-menu')
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def shoot():
    try:
        windows = sorted((w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()), key=lambda w: w.width() * w.height())
        result['windows'] = [(w.windowTitle(), w.width(), w.height()) for w in windows]
        windows[0].grab().save(str(out / 'file_menu.png'))
    except Exception:
        result['shot_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


try:
    lx.eval('attr.formPopover {69223020078:sheet}')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(4000, shoot)
