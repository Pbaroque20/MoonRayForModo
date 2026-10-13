# python
"""Isolated GUI test: the picture's right-click menu, pictured, with what it lists and what Smart Render offers."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/picture-menu'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def look():
    try:
        from moonray_modo.panel import Panel
        panel = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
        lx.eval('moonray.render.smart_render 2')
        # As a right-click on the picture does.
        place = QtCore.QPoint(panel.preview.width() // 3, panel.preview.height() // 3)
        menu = held['menu'] = panel._image_menu(place)
        result['entries'] = [action.text() or '(divider)' for action in menu.actions()]
        result['smart'] = [(action.text(), action.isChecked()) for action in panel._smart_menu.actions()]
        result['safe'] = [(action.text(), action.isChecked()) for action in panel._safe_menu.actions()]
        menu.popup(panel.preview.mapToGlobal(place))
        QtWidgets.QApplication.processEvents()
        smart = next(action for action in menu.actions() if action.text() == 'Smart Render')
        menu.setActiveAction(smart)
        panel._smart_menu.popup(menu.mapToGlobal(menu.actionGeometry(smart).topRight()))
        QtCore.QTimer.singleShot(800, shoot)
    except Exception:
        result['error'] = traceback.format_exc()
        done()


def shoot():
    try:
        from moonray_modo.panel import Panel
        panel = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
        menu, smart = held['menu'], panel._smart_menu
        area = menu.frameGeometry().united(smart.frameGeometry()).adjusted(-12, -12, 12, 12)
        QtGui.QGuiApplication.primaryScreen().grabWindow(0, area.x(), area.y(), area.width(), area.height()).save(str(out / 'menu.png'))
        smart.close()
        menu.close()
    except Exception:
        result['error'] = traceback.format_exc()
    done()


def done():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    lx.eval('!app.quit')


try:
    lx.eval('item.create mesh')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(7000, look)
