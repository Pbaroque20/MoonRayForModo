# python
"""GUI: pictures of PBR validity for the README. dragon_test.lxo opened with Diagnostics > PBR validity output on (the
test profile's own settings), rendered in the preview window by XPU2 and by MoonRay XPU; the window grabbed with the
PBR validity picture and with the beauty. Writes test-results/pbr-validity-shots/. The settings are put back after."""
import json
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/pbr-validity-shots'
out.mkdir(parents=True, exist_ok=True)
SCENE = r'C:\Users\Raphael Tobar\Downloads\dragon_test.lxo'
result = {'steps': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def settings():
    from moonray_modo import native
    return QtCore.QSettings('MoonRayForModo', native.settings_name())


held = {}
try:
    s = settings()
    for key in ('pbr_validity', 'xpu2/renderer'):
        held[key] = s.value(key)
    s.setValue('pbr_validity', True)
    s.setValue('xpu2/renderer', 'xpu2')
    s.sync()
    lx.eval('scene.open {%s}' % SCENE)
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def panel():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def grab(name):
    p = panel()
    QtWidgets.QApplication.processEvents()
    p.window().grab().save(str(out / (name + '.png')))
    result['steps'].append([name, p.buffer.currentData(), p.status.text(), p.image_info.text(), p.render_timing.text()])
    save()


def render(label, then):
    try:
        p = panel()
        engine = p.preview_engine.findData('moonray')
        if engine >= 0: p.preview_engine.setCurrentIndex(engine)
        p._preferences_followed_now()
        p.render_once()
        began = time.monotonic()
        result['steps'].append([label, 'started', p.status.text()])
        save()

        def wait():
            try:
                q = panel()
                if (getattr(q, '_rendering', False) and time.monotonic() - began < 300) or time.monotonic() - began < 4:
                    QtCore.QTimer.singleShot(2000, wait); return
                QtCore.QTimer.singleShot(1500, then)
            except Exception:
                result['wait_error'] = traceback.format_exc(); save()
        QtCore.QTimer.singleShot(3000, wait)
    except Exception:
        result[label + '_error'] = traceback.format_exc(); save()


def shoot(shots, then):
    """Each (buffer, picture name) in turn: the buffer chosen, then grabbed once the window has drawn it."""
    if not shots:
        then(); return
    (key, name), rest = shots[0], shots[1:]
    try:
        p = panel()
        p.buffer.setCurrentIndex(p.buffer.findData(key))
    except Exception:
        result['shoot_error'] = traceback.format_exc(); save()
    QtCore.QTimer.singleShot(6000, lambda: (grab(name), shoot(rest, then)))


def xpu2_done():
    def next_render():
        s = settings(); s.setValue('xpu2/renderer', 'xpu'); s.sync()
        render('xpu', xpu_done)
    shoot([('pbr_validity', 'xpu2-pbr-validity'), ('beauty', 'xpu2-beauty')], next_render)


def xpu_done():
    shoot([('pbr_validity', 'xpu-pbr-validity'), ('beauty', 'xpu-beauty')], finish)


def finish():
    try:
        s = settings()
        for key, value in held.items():
            if value is None: s.remove(key)
            else: s.setValue(key, value)
        s.sync()
        panel().stop()
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(3000, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(8000, lambda: render('xpu2', xpu2_done))
