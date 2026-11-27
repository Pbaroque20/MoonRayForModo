# python
"""GUI: two scenes open in Modo, switched between with the MoonRay preview open (his report 2026-11-26: switching
between two open scenes crashes Modo). Scene A: a cube, the preview open, PROBE_ENGINE (xpu2, moonlightipr, moonray;
default the panel's own) in realtime when PROBE_RT=1. Scene B: a new scene with a sphere. Then the current scene
switched A, B, A, ... (PROBE_SWITCHES, default 8), PROBE_WAIT ms apart, and Modo quit. The exit code says whether it
crashed (1 a clean scripted quit); report.json each step and any fault. Writes test-results/scene-switch-gui/<tag>.
Run with tools/launch_gui_probe.py probe_gui_scene_switch.py --wait."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore

tag = os.environ.get('PROBE_TAG', 'run')
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\scene-switch-gui') / tag
out.mkdir(parents=True, exist_ok=True)
WAIT = int(os.environ.get('PROBE_WAIT', '2500'))
SWITCHES = int(os.environ.get('PROBE_SWITCHES', '8'))
report = {'tag': tag, 'steps': [], 'errors': []}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def step(name, **values):
    report['steps'].append(dict(values, step=name))
    save()


def guarded(fn):
    def run():
        try:
            fn()
        except Exception:
            report['errors'].append(traceback.format_exc()[-1500:])
            save()
    return run


def scenes():
    """The open scenes' names, as the sceneservice lists them."""
    count = lx.eval('query sceneservice scene.N ?')
    return [lx.eval('query sceneservice scene.name ? %d' % i) for i in range(count)]


def current_name():
    import modo
    scene = modo.Scene()
    return scene.name


def make(shape):
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.%s on' % shape)
    lx.eval('tool.apply')
    lx.eval('tool.set prim.%s off' % shape)


def panel():
    from moonray_modo.panel import live_panels
    found = live_panels()
    return found[0] if found else None


@guarded
def first():
    make('cube')
    lx.eval('moonray.open')
    step('scene A made, preview opened', scene=current_name())
    QtCore.QTimer.singleShot(WAIT, realtime)


@guarded
def realtime_body():
    p = panel()
    engine = os.environ.get('PROBE_ENGINE')
    if p is not None and engine:
        p.preview_engine.setCurrentIndex(p.preview_engine.findData(engine))
    if p is not None and os.environ.get('PROBE_RT') == '1' and not p.rt.isChecked():
        p.rt.click()
    step('realtime', engine=engine, rt=bool(p and p.rt.isChecked()))


def realtime():
    realtime_body()
    QtCore.QTimer.singleShot(WAIT * 2, second)


@guarded
def second_body():
    p = panel()
    # PROBE_STOP_FIRST=1: realtime off before the second scene; =close: the preview window closed too.
    stop = os.environ.get('PROBE_STOP_FIRST')
    if stop and p is not None and p.rt.isChecked():
        p.rt.click()
    if stop == 'close' and p is not None:
        p.window().close()
    step('before scene B', stop=stop)
    lx.eval('scene.new')
    make('sphere')
    step('scene B made', scene=current_name(), scenes=len(scenes()))


def second():
    second_body()
    QtCore.QTimer.singleShot(WAIT, lambda: switch(0))


_stacks = []


def switch(n):
    if not _stacks:
        # Every Python thread's stack, written should Modo hang (or die in Python) from here on.
        import faulthandler
        _stacks.append(open(out / 'stacks.txt', 'w'))
        faulthandler.enable(file=_stacks[0], all_threads=True)
        faulthandler.dump_traceback_later(15, repeat=True, file=_stacks[0])
    if n >= SWITCHES:
        QtCore.QTimer.singleShot(WAIT, quit_now)
        return
    listed = scenes()
    target = listed[n % len(listed)]
    ident = lx.eval('query sceneservice scene.id ? %d' % (n % len(listed)))
    ways = ['scene.set "%s"' % ident, 'scene.set %s' % ident, 'scene.set "%s"' % target, 'scene.set %d' % (n % len(listed))]
    for how in ways:
        try:
            lx.eval(how)
        except Exception:
            report['errors'].append(how + ': ' + traceback.format_exc()[-600:])
            continue
        if current_name() == target or current_name() == ident:
            step('switched', n=n, to=target, by=how)
            break
    else:
        step('not switched', n=n, wanted=target, now=current_name(), scenes=listed)
    QtCore.QTimer.singleShot(WAIT, lambda: switch(n + 1))


def quit_now():
    p = panel()
    try:
        if p is not None and p.rt.isChecked():
            p.rt.click()
    except Exception:
        pass
    step('quitting')
    lx.eval('!app.quit')


def look_for_dialogs():
    """A modal window open (its nested event loop still runs this timer): what it says, and the stack that opened it.
    PROBE_CLOSE_DIALOGS=1 closes it, to see what follows."""
    from PySide2 import QtWidgets
    import sys
    modal = QtWidgets.QApplication.activeModalWidget()
    if modal is not None:
        text = modal.text() if hasattr(modal, 'text') else ''
        frames = []
        frame = sys._getframe()
        import traceback as tb
        stacks = {}
        for tid, top in sys._current_frames().items():
            stacks[str(tid)] = ''.join(tb.format_stack(top))[-3000:]
        step('modal dialog', kind=type(modal).__name__, title=modal.windowTitle(), text=text, stacks=stacks)
        if os.environ.get('PROBE_CLOSE_DIALOGS') == '1':
            modal.reject() if hasattr(modal, 'reject') else modal.close()
            return
    QtCore.QTimer.singleShot(3000, look_for_dialogs)


_watch = QtCore.QTimer()
QtCore.QTimer.singleShot(3000, look_for_dialogs)
QtCore.QTimer.singleShot(1500, first)
