# python
"""Isolated GUI test: what holds on to the objects that grow with each MoonRay render.

Two balls, rendered with MoonRay several times. Then, for each kind of object found to grow (Python's stand-ins for
threads Python did not start, Qt byte arrays, Modo items), the newest few are taken and what refers to them is
written down, two steps back: which containers, and where those live."""
import gc
import json
import os
import pathlib
import threading
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/memory-holders'
out.mkdir(parents=True, exist_ok=True)
result = {}
RENDERS = 6


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def describe(thing):
    kind = type(thing).__name__
    if isinstance(thing, dict):
        keys = list(thing.keys())[:6]
        owner = thing.get('__name__') or thing.get('__qualname__')
        return 'dict%s keys=%s' % ((' of module ' + owner) if owner else '', [str(k)[:30] for k in keys])
    if isinstance(thing, (list, tuple, set)):
        return '%s len=%d' % (kind, len(thing))
    if hasattr(thing, '__func__') or callable(thing):
        return '%s %s' % (kind, getattr(thing, '__qualname__', getattr(thing, '__name__', ''))[:60])
    return '%s %s' % (kind, repr(thing)[:60])


def holders(objects, frame):
    found = []
    for thing in objects:
        first = []
        for referrer in gc.get_referrers(thing):
            if referrer is objects or referrer is frame or isinstance(referrer, type(frame)):
                continue
            second = [describe(r) for r in gc.get_referrers(referrer)[:6] if r is not objects and not isinstance(r, type(frame))]
            first.append({'by': describe(referrer), 'which_is_held_by': second[:4]})
        found.append({'object': describe(thing), 'held_by': first[:6]})
    return found


def analyse():
    gc.collect()
    import sys
    frame = sys._getframe()
    every = gc.get_objects()
    dummies = [o for o in every if type(o).__name__ == '_DummyThread']
    arrays = [o for o in every if type(o).__name__ == 'QByteArray']
    items = [o for o in every if type(o).__name__ == 'Item' and type(o).__module__.startswith('modo')]
    result['counts'] = {'dummy_threads': len(dummies), 'qbytearrays': len(arrays), 'modo_items': len(items),
                        'threading_active': len(threading._active)}
    result['dummy_threads'] = holders(dummies[-3:], frame)
    result['qbytearrays'] = holders(arrays[-4:], frame)
    result['qbytearray_sizes'] = sorted((a.size() for a in arrays), reverse=True)[:10]
    result['modo_items'] = holders(items[-3:], frame)
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(2000)
def begin():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))


for index in range(RENDERS):
    @step(14000)
    def render(index=index):
        panel_widget().start.click()


@step(500)
def finish_():
    analyse()


def run(index=0):
    if index >= len(STEPS):
        save()
        lx.eval('!!app.quit')
        return
    function, wait = STEPS[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append([function.__name__, traceback.format_exc()])
        save()
    QtCore.QTimer.singleShot(wait, lambda: run(index + 1))


try:
    for x in (-.6, .6):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(8000, lambda: run())
