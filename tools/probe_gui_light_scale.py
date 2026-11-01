# python
"""Isolated GUI test: a MoonRay DiskLight, or another round light (MOONRAY_LIGHT_CLASS), under a parent with an uneven scale
(MOONRAY_LIGHT_SCALE uneven), against the same parent unscaled (even), and with no light (none), on XPU2, MoonRay XPU and MoonLightIPR.
XPU2 used to refuse the uneven one and MoonRay to switch it off. Writes test-results/light-scale/<class>-<scale>.json."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/light-scale'
out.mkdir(parents=True, exist_ok=True)
kind = os.environ.get('MOONRAY_LIGHT_CLASS', 'DiskLight')
scale = os.environ.get('MOONRAY_LIGHT_SCALE', 'uneven')
report = out / ('%s-%s.json' % (kind, scale))
result = {'runs': {}}
held = {'to do': ['xpu2', 'xpu', 'moonlightipr']}


def save():
    report.write_text(json.dumps(result, default=str))


def later(ms, step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            result['done'] = True
        save()
    QtCore.QTimer.singleShot(ms, run)


def setup():
    from moonray_modo import entities
    scene = modo.Scene()
    mesh = scene.addMesh('Box')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.reset')
    for axis, value in (('cenX', 0), ('cenY', 0), ('cenZ', 0), ('sizeX', 3), ('sizeY', 3), ('sizeZ', .2)):
        lx.eval('tool.attr prim.cube %s %s' % (axis, value))
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.cube off')
    for name, value in (('resX', 320), ('resY', 180)):
        scene.renderItem.channel(name).set(value)
    modo.LocatorSuperType(scene.renderCamera).position.set((0, 0, 8))
    modo.LocatorSuperType(scene.renderCamera).rotation.set((0, 0, 0))
    if scale != 'none':
        before = {item.id for item in entities.items_of(scene, kind)}
        lx.eval('moonray.entity.add ' + kind)
        light = next(item for item in entities.items_of(scene, kind) if item.id not in before)
        parent = scene.addItem('locator')
        if scale == 'uneven':
            modo.LocatorSuperType(parent).scale.set((2, .5, 1))
        light.setParent(parent)
        modo.LocatorSuperType(light).position.set((0, 0, 2))
        result['scale read'] = [float(v) for v in __import__('moonray_modo.host', fromlist=['world_matrix']).world_matrix(light)]
    lx.eval('moonray.page preview')
    later(3000, next_run)


def next_run():
    from moonray_modo.panel import Panel
    panel = held['panel'] = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
    if not held['to do']:
        panel.preferences.set('xpu2/renderer', 'xpu2')
        result['done'] = True
        return
    engine = held['now'] = held['to do'].pop(0)
    panel.preferences.set('xpu2/renderer', 'xpu' if engine == 'xpu' else 'xpu2')
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr' if engine == 'moonlightipr' else 'moonray'))
    if engine == 'moonlightipr':
        panel.rt.setChecked(True)
        later(8000, finished)
    else:
        panel.start.click()
        later(1000, lambda: wait(240))


def wait(tries):
    if held['panel']._rendering and tries > 0:
        later(500, lambda: wait(tries - 1))
    else:
        later(3000, finished)


def finished():
    panel = held['panel']
    image = panel.preview.image
    grid = []
    if not image.isNull():
        for y in range(0, image.height(), 6):
            for x in range(0, image.width(), 6):
                colour = image.pixelColor(x, y)
                grid.append(max(colour.red(), colour.green(), colour.blue()))
        image.save(str(out / ('%s-%s-%s.png' % (kind, scale, held['now']))))
    log = panel.renderer.log
    result['runs'][held['now']] = {'status': panel.status.text(), 'xpu2': getattr(panel.renderer.session, 'xpu2_active', None), 'grid': grid,
                                   'refused': 'non-uniform' in log.lower(), 'switched off': 'setting to off' in log}
    if held['now'] == 'moonlightipr':
        panel.rt.setChecked(False)
    later(2000, next_run)


# Here, in the script's own command: Modo refuses a scene's edits from a timer.
try:
    setup()
except Exception:
    result['errors'] = [traceback.format_exc()]
    result['done'] = True
save()
