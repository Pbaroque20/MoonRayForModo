# python
"""Isolated GUI test: what the preview is titled. Its own window is MoonRay Preview; the view inside is MoonRay."""
import ctypes
import ctypes.wintypes
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/window-title'
out.mkdir(parents=True, exist_ok=True)
result = {}


def titles():
    """The titles of this Modo's own top-level windows, as Windows has them."""
    found = []
    user = ctypes.windll.user32

    def each(handle, _):
        process = ctypes.wintypes.DWORD()
        user.GetWindowThreadProcessId(handle, ctypes.byref(process))
        if process.value == os.getpid() and user.IsWindowVisible(handle):
            text = ctypes.create_unicode_buffer(256)
            user.GetWindowTextW(handle, text, 256)
            if text.value:
                found.append(text.value)
        return True
    user.EnumWindows(ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)(each), 0)
    return found


def look():
    try:
        from moonray_modo.panel import Panel
        panel = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
        result['windows'] = titles()
        result['view_name'] = lx.service.Host().LookupServer('customview', 'MoonRayForModoPreview', 0) is not None
        try:
            tag = lx.object.Factory(lx.service.Host().LookupServer('customview', 'MoonRayForModoPreview', 0)).UserName()
            result['view_user_name'] = tag
        except Exception as exc:
            result['view_user_name'] = 'cannot be asked: ' + str(exc)
        screen = QtGui.QGuiApplication.primaryScreen()
        frame = panel.window().frameGeometry()
        screen.grabWindow(0, frame.x() - 12, frame.y() - 60, frame.width() + 24, 140).save(str(out / 'title.png'))
    except Exception:
        result['error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    lx.eval('!app.quit')


try:
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(7000, look)
