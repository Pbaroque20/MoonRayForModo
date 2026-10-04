"""Read mouse-button state without consuming Modo input or Qt event wrappers."""
import ctypes,sys
_key_state=None
if sys.platform=='win32':
    _key_state=ctypes.WinDLL('user32',use_last_error=True).GetAsyncKeyState
    _key_state.argtypes=[ctypes.c_int];_key_state.restype=ctypes.c_short

def dragging():
    if _key_state is not None:
        return any(_key_state(key)&0x8000 for key in (1,2,4))
    from PySide2 import QtCore,QtGui
    return QtGui.QGuiApplication.mouseButtons()!=QtCore.Qt.NoButton
