# python
"""Isolated GUI test of a report: a render through a dwPerspectiveCamera comes out black. A new scene with a cube at the origin and a
sun; each way of having the camera rendered through on XPU2, MoonRay XPU and MoonLightIPR; how bright each picture is.
Writes test-results/camera-black/."""
import json
import pathlib
import shutil
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/camera-black'
shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True, exist_ok=True)
result = {'runs': {}}
held = {'cameras': {}}
ENGINES = ('xpu2', 'xpu', 'moonlightipr')


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def later(ms, step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            result['done'] = True
        save()
    QtCore.QTimer.singleShot(ms, run)


def added(placed, kind='PerspectiveCamera'):
    """A new camera from the menu's command, moved or left where it is made."""
    from moonray_modo import entities
    scene = modo.Scene()
    before = {item.id for item in entities.items_of(scene, kind)}
    lx.eval('moonray.entity.add ' + kind)
    item = next(item for item in entities.items_of(scene, kind) if item.id not in before)
    if placed:
        modo.LocatorSuperType(item).position.set(placed)
    return item


def converted(kind='PerspectiveCamera'):
    """Another Modo camera, placed, then Convert to MoonRay Camera."""
    from moonray_modo.camera_convert import KINDS
    scene = modo.Scene()
    camera = scene.addItem('camera')
    modo.LocatorSuperType(camera).position.set((0, 0, 4))
    scene.select(camera)
    lx.eval('moonray.camera.convert %d' % [name for name, _ in KINDS].index(kind))
    return scene.selected[-1]


def bake(mesh):
    """A bake camera, which has no view: it renders the mesh it is told of from its UVs."""
    from moonray_modo import entities
    item = added(None, 'BakeCamera')
    item.channel(entities.CHANNEL_PREFIX + 'geometry').set(mesh.name)
    return item


def setup():
    scene = modo.Scene()
    mesh = scene.addMesh('Box')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.reset')
    for axis, value in (('cenX', 0), ('cenY', 0), ('cenZ', 0), ('sizeX', 1), ('sizeY', 1), ('sizeZ', 1)):
        lx.eval('tool.attr prim.cube %s %s' % (axis, value))
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.cube off')
    for name, value in (('resX', 320), ('resY', 180)):
        scene.renderItem.channel(name).set(value)
    modo.LocatorSuperType(scene.renderCamera).position.set((0, 0, 4))
    modo.LocatorSuperType(scene.renderCamera).rotation.set((-.05, .05, 0))
    scene.addItem('sunLight')
    from moonray_modo import entities, host
    # Where a new camera stands: against the render camera, and against a camera with a parent that is moved and turned.
    new = added(None)
    result['new camera against the render camera'] = max(abs(a - b) for a, b in zip(host.world_matrix(new), host.world_matrix(scene.renderCamera)))
    parent = scene.addItem('locator')
    modo.LocatorSuperType(parent).position.set((1, 2, 3))
    modo.LocatorSuperType(parent).rotation.set((.3, .2, .1))
    child = scene.addItem('camera')
    child.setParent(parent)
    modo.LocatorSuperType(child).position.set((0, 0, 5))
    other = added(None)
    entities.stand_like(other, child)
    result['new camera against a parented one'] = max(abs(a - b) for a, b in zip(host.world_matrix(other), host.world_matrix(child)))
    held['parented'] = (other, child, parent)
    held['cameras'] = {'modo camera': None}
    for kind in ('PerspectiveCamera', 'OrthographicCamera', 'FisheyeCamera', 'SphericalCamera', 'DomeMaster3DCamera'):
        for words, make in (('at 0 0 4', lambda: added((0, 0, 4), kind)), ('not moved', lambda: added(None, kind)),
                            ('at 0 0 1.2', lambda: added((0, 0, 1.2), kind)), ('converted at 0 0 4', lambda: converted(kind))):
            try:
                held['cameras'][kind + ' ' + words] = make()
            except Exception:
                result.setdefault('not made', {})[kind + ' ' + words] = traceback.format_exc()
    try:
        held['cameras']['BakeCamera of the box'] = bake(mesh)
    except Exception:
        result.setdefault('not made', {})['BakeCamera'] = traceback.format_exc()
    held['to do'] = [(engine, name) for engine in ENGINES for name in held['cameras']]
    import os
    if os.environ.get('MOONRAY_CAMERA_REPEAT'):
        # Named cases only, each engine three times, against one another.
        wanted = os.environ['MOONRAY_CAMERA_REPEAT'].split('|')
        held['to do'] = [(engine, name) for _ in range(3) for engine, name in held['to do'] if name in wanted]
        result['runs by order'] = []
    lx.eval('moonray.page preview')
    later(3000, next_run)


def choose(chosen):
    """Which camera is rendered through, as the preview window's menu chooses it: Modo refuses an edit made directly from a timer."""
    from moonray_modo import camera_choice
    wanted = chosen.id if chosen is not None else ''
    lx.eval('moonray.camera %d' % [identity for _, identity in camera_choice.choices()].index(wanted))


def next_run():
    from moonray_modo.panel import Panel
    panel = held['panel'] = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
    if 'parented' in held:
        # Read again once Modo has evaluated the scene.
        from moonray_modo import host
        other, child, parent = held.pop('parented')
        result['parented, read later'] = {'difference': max(abs(a - b) for a, b in zip(host.world_matrix(other), host.world_matrix(child))),
                                          'new': host.world_matrix(other), 'theirs': host.world_matrix(child),
                                          'new parent': other.parent.id if other.parent else None, 'their parent': child.parent.id if child.parent else None,
                                          'new local': modo.LocatorSuperType(other).position.get(), 'their local': modo.LocatorSuperType(child).position.get()}
        if __import__('os').environ.get('MOONRAY_CAMERA_PLACE_ONLY'):
            held['to do'] = []
    if not held['to do']:
        panel.preferences.set('xpu2/renderer', 'xpu2')
        result['done'] = True
        return
    engine, name = held['now'] = held['to do'].pop(0)
    choose(held['cameras'][name])
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
        finished()


def brightness(image):
    total, top, count = 0.0, 0, 0
    for y in range(0, image.height(), 4):
        for x in range(0, image.width(), 4):
            colour = image.pixelColor(x, y)
            level = max(colour.red(), colour.green(), colour.blue())
            total += level
            top = max(top, level)
            count += 1
    return round(total / max(1, count), 2), top


def finished():
    panel = held['panel']
    engine, name = held['now']
    key = engine + ' / ' + name
    # A picture not yet in the preview as the render ends: said, and looked for again once.
    if panel.preview.image.isNull() and held.get('looked again') != key:
        held['looked again'] = key
        result.setdefault('no picture as the render ended', []).append(key)
        later(4000, finished)
        return
    entry = {'status': panel.status.text(), 'xpu2': getattr(panel.renderer.session, 'xpu2_active', None)}
    if not panel.preview.image.isNull():
        entry['mean, brightest'] = brightness(panel.preview.image)
        panel.preview.image.save(str(out / (key.replace(' / ', '-').replace(' ', '_').replace(',', '') + '.png')))
    entry['log tail'] = panel.renderer.log[-500:]
    result['runs'][key] = entry
    if 'runs by order' in result:
        result['runs by order'].append((key, entry.get('mean, brightest')))
    if engine == 'moonlightipr':
        panel.rt.setChecked(False)
    later(2000, next_run)


# Here, in the script's own command: Modo refuses a scene's edits from a timer.
try:
    setup()
except Exception:
    result['errors'] = [traceback.format_exc()]
    result['done'] = True
save()
