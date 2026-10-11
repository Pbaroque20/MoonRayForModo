# python
"""Isolated GUI test: a MoonRay MeshLight item whose mesh is chosen from its properties lights the scene.

A ground and a slab above it are made and the preview started with nothing but the sky lighting them. While the
preview runs, a MeshLight item is added and the slab chosen as its mesh through the item's own popup, as a user chooses
it. How bright the picture is before and after is written down, for each engine; the second engine has the item
already and only the mesh is chosen while it runs."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/mesh-light'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def brightness(panel):
    """The mean of the picture's lower half, where the ground is, from a grid of its pixels."""
    image = panel.preview.image
    if image is None or image.isNull():
        return None
    total = count = 0
    for j in range(12, 24):
        for i in range(24):
            colour = QtGui.QColor(image.pixel(int((i + .5) * image.width() / 24), int((j + .5) * image.height() / 24)))
            total += colour.red() + colour.green() + colour.blue()
            count += 3
    return round(total / count, 1)


def pick(index):
    scene = modo.Scene()
    scene.select(held['lamp'])
    lx.eval('%s %d' % (held['command'], index))


def add_lamp():
    from moonray_modo import entities
    from lxserv import moonray_entities  # noqa: F401
    scene = modo.Scene()
    lx.eval('moonray.entity.add MeshLight')
    lamp = scene.selected[0]
    result['lamp'] = [lamp.name, lamp.type, lamp.channel(entities.CHANNEL_PREFIX + 'intensity').get()]
    held['lamp'] = lamp
    kinds = list(entities.classes())
    i = kinds.index('MeshLight')
    j = next(index for index, (key, _, _, _, _) in enumerate(entities.channels('MeshLight')) if key == 'geometry')
    held['command'] = 'moonray.entity.pick%d_%d' % (i, j)
    names = sorted({item.name for item in scene.items('mesh', superType=False)})
    result['offered'] = names
    held['slab'] = names.index('Slab') + 1
    pick(held['slab'])
    result['channel'] = lamp.channel(entities.CHANNEL_PREFIX + 'geometry').get()


try:
    scene = modo.Scene()
    for name, values in (('Ground', dict(cenY=-.05, sizeX=8, sizeY=.1, sizeZ=8)), ('Slab', dict(cenY=1.2, sizeX=.8, sizeY=.8, sizeZ=.8))):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.cube on')
        for key, value in values.items():
            lx.eval('tool.attr prim.cube %s %s' % (key, value))
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
        scene.selected[0].name = name
        held[name] = scene.selected[0]
    # Modo's own light off, so that what lights the ground is the sky, and then the slab.
    for light in scene.items('light'):
        light.channel('render').set('off')
    camera = scene.renderCamera
    camera.position.set((0.0, 3.0, 9.0))
    camera.rotation.set((-.3, 0.0, 0.0))
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def begin(name, change, then, wait):
    """Start an engine's preview, and after a while note the picture, make the change, and after as long again go on."""
    try:
        panel = panel_widget()
        held.setdefault('stored', panel.preferences.store.value('runtime', ''))
        held.setdefault('engine', panel.preview_engine.currentData())
        # The test follows the scene, whatever the window was last left at; it is put back at the end.
        held.setdefault('live', panel.ipr_mode.isChecked())
        panel.ipr_mode.setChecked(True)
        panel.preferences.set('runtime', str(root / 'runtime/steady-0350-pool'))
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(name))
        QtWidgets.QApplication.processEvents()
        if panel.start.text() == 'Render':
            panel.start.click()
    except Exception:
        result[name + '_error'] = traceback.format_exc()
    save()

    def changed():
        try:
            panel = panel_widget()
            result[name + '_before'] = brightness(panel)
            panel.window().grab().save(str(out / (name + '_before.png')))
            change()
        except Exception:
            result[name + '_change_error'] = traceback.format_exc()
        save()
        QtCore.QTimer.singleShot(wait, after)

    def after():
        try:
            panel = panel_widget()
            result[name + '_after'] = brightness(panel)
            result[name] = [panel.status.text(), panel.warnings.toPlainText()[:500]]
            panel.window().grab().save(str(out / (name + '_after.png')))
        except Exception:
            result[name + '_after_error'] = traceback.format_exc()
        save()
        then()

    QtCore.QTimer.singleShot(wait, changed)


def first():
    begin('moonlightipr', add_lamp, second, 20000)


def second():
    try:
        # The item stays; its mesh is un-chosen, to be chosen again while MoonRay's preview runs.
        pick(0)
    except Exception:
        result['second_error'] = traceback.format_exc()
    begin('moonray', lambda: pick(held['slab']), third, 60000)


def third():
    """MoonRay's preview stopped and started again with the mesh already chosen: what a fresh export shows."""
    try:
        from moonray_modo import host, rdla
        taken = host.snapshot(refresh_materials=True)
        text = rdla.scene_text(taken, 320, 180, 2, 0.0, str(out / 'check.exr'))
        (out / 'check.rdla').write_text(text)
        result['written'] = [line.strip()[:200] for line in text.splitlines() if 'MeshLight' in line or 'meshLight' in line][:8]
        panel = panel_widget()
        panel.start.click()
        QtWidgets.QApplication.processEvents()
        panel.start.click()
    except Exception:
        result['third_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(60000, last)


def last():
    try:
        panel = panel_widget()
        result['moonray_restarted'] = brightness(panel)
        panel.window().grab().save(str(out / 'moonray_restarted.png'))
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        panel.preferences.store.setValue('runtime', held['stored'])
        panel.ipr_mode.setChecked(held['live'])
    except Exception:
        result['last_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(5000, first)
