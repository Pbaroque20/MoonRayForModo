# python
"""Isolated GUI test: Modo's File menu and the MoonRay menu, each shown on its own (attr.formPopover) and pictured
whole. The File menu should be Modo's own, untouched by the kit; the MoonRay menu should hold Export as MoonRay Scene
after Import MaterialX Material. The preview window's Options menu is listed too."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\file-menu')
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('*.png'):
    old.unlink()
result = {}
SHEETS = (('File', '69223020078:sheet'), ('MoonRay', 'MoonRayForModoMenu:sheet'))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def shown():
    return [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()]


def show(index=0):
    if index >= len(SHEETS):
        QtCore.QTimer.singleShot(500, options)
        return
    try:
        lx.eval('attr.formPopover {%s}' % SHEETS[index][1])
    except Exception:
        result['error_' + SHEETS[index][0]] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(3000, lambda: shoot(index))


def shoot(index):
    title = SHEETS[index][0]
    try:
        windows = shown()
        result['windows_' + title] = [(w.windowTitle(), w.width(), w.height()) for w in windows]
        popover = next(w for w in windows if w.windowTitle() == title)
        popover.grab().save(str(out / ('%s_menu.png' % title.lower())))
        popover.close()
    except Exception:
        result['shot_error_' + title] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1000, lambda: show(index + 1))


def options():
    try:
        lx.eval('moonray.open')
    except Exception:
        result['open_error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(4000, list_options)


def list_options():
    try:
        from moonray_modo.panel import Panel
        panel = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
        menu = panel._options_menu() if hasattr(panel, '_options_menu') else None
        result['options'] = [a.text() for a in menu.actions()] if menu is not None else 'no _options_menu'
    except Exception:
        result['options_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(4000, show)
