# python
"""Isolated GUI test: the compile button and the shaders' state look again without the form being left. The XPU2 form open, the
press's state is set with no compile started, and the screen is taken before, during and after, with the mouse left alone.
Writes test-results/compile-button/report.json and its pictures."""
import gc
import json
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/compile-button'
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def picture(name):
    QtWidgets.QApplication.primaryScreen().grabWindow(0).save(str(out / (name + '.png')))


def server():
    """The kit's module for these commands, however Modo imported it."""
    for held in gc.get_objects():
        if isinstance(held, type) and held.__name__ == 'ShadersNotifier':
            import sys
            return sys.modules.get(held.__module__) or held
    raise LookupError('ShadersNotifier')


def look(name, module):
    result[name] = {'state': module.state(), 'button': module.button_name(module.state()),
                    'clients': len(module.ShadersNotifier.clients)}
    picture(name)
    save()


def guarded(call):
    def run():
        try:
            call()
        except Exception:
            result['error'] = traceback.format_exc()
            save()
            lx.eval('!app.quit')
    return run


def before():
    module = server()
    held['module'] = module
    look('before', module)
    module._pressed[0] = time.monotonic()
    module._watch()
    module._notify()
    QtCore.QTimer.singleShot(1000, guarded(pressed))


def pressed():
    look('pressed', held['module'])
    QtCore.QTimer.singleShot(6000, guarded(after))


def after():
    look('after', held['module'])
    result['done'] = True
    save()
    QtCore.QTimer.singleShot(200, lambda: lx.eval('!app.quit'))


held = {}
QtCore.QTimer.singleShot(4000, guarded(before))
try:
    lx.eval('attr.formPopover {MoonRayXPU2:sheet}')
except Exception:
    result['open'] = traceback.format_exc()
    save()
