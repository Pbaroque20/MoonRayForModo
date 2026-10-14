# python
"""Isolated GUI test: the Properties panel of a MoonRay light and a MoonRay camera, and whether their position,
rotation and scale can be set channel by channel.

A MoonRay SphereLight and a PerspectiveCamera are added. Each is selected and Modo's window pictured, with the forms
that Modo's Properties panel shows for it written down. Then the commands a transform's X, Y and Z fields run are
tried on each: position, rotation and scale set, read back, and the item's world place read."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/entity-transform'
out.mkdir(parents=True, exist_ok=True)
result = {'items': {}}
held = {}
KINDS = os.environ.get('MOONRAY_PROBE_KINDS', 'SphereLight,PerspectiveCamera').split(',')


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def window():
    shown = [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()]
    return max(shown, key=lambda w: w.width() * w.height())


def tried(item, kind):
    entry = result['items'].setdefault(kind, {})
    entry['type'] = item.type
    try:
        entry['channels'] = [n for n in (item.channelNames if hasattr(item, 'channelNames') else []) if n.split('.')[0] in ('pos', 'rot', 'scl')][:12]
    except Exception:
        entry['channels'] = None
    for name, command in (('position', 'transform.channel pos.%s %s'), ('rotation', 'transform.channel rot.%s %s'), ('scale', 'transform.channel scl.%s %s')):
        values = {'X': 1.25, 'Y': 2.5, 'Z': -0.75} if name != 'scale' else {'X': 2.0, 'Y': 3.0, 'Z': 4.0}
        outcome = {}
        for axis, value in values.items():
            try:
                lx.eval('!select.item {%s} set' % item.id)
                lx.eval('!' + command % (axis, value))
                outcome[axis] = lx.eval('transform.channel %s.%s ?' % (('pos', 'rot', 'scl')[('position', 'rotation', 'scale').index(name)], axis))
            except Exception as exc:
                outcome[axis] = 'failed: %s' % exc
        entry[name] = outcome
    try:
        entry['world_position'] = [round(v, 4) for v in modo.LocatorSuperType(item).position.get()] if hasattr(modo, 'LocatorSuperType') else None
    except Exception as exc:
        entry['world_position'] = 'failed: %s' % exc
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


for kind in KINDS:
    @step(2500)
    def show(kind=kind):
        lx.eval('!select.item {%s} set' % held[kind].id)

    @step(1500)
    def picture(kind=kind):
        window().grab().save(str(out / ('%s_properties.png' % kind)))
        tried(held[kind], kind)


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
    scene = modo.Scene()
    for kind in KINDS:
        before = {i.id for i in scene.items()}
        lx.eval('moonray.entity.add %s' % kind)
        made = [i for i in scene.items() if i.id not in before and i.type.startswith('moonray.')]
        held[kind] = made[0]
    # Modo's Properties panel in view: the layout's own.
    lx.eval('!layout.restore default')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(6000, lambda: run())
