# python
"""Isolated GUI test: an albedo image chosen in a MoonRay material's properties shows, also where the material's group
sits inside a group tied to the item.

A ball with UVs is given a DwaBaseMaterial by the plugin's own assign, and a chequered image is chosen for its albedo
as the properties' popup chooses one. What the scene holds of it is written down and the preview pictured. The
material's group is then moved inside a group tied to the ball itself, as an imported scene has it, and the same is
done again."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/masked-image'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def taken(name):
    """What a snapshot holds of the ball's material and its UVs."""
    from moonray_modo import host
    scene = host.snapshot(refresh_materials=True)
    found = {'materials': sorted(scene['materials']), 'native': sorted(scene.get('native_materials', {})), 'warnings': scene['warnings'][:6]}
    found['meshes'] = [[m.get('name'), m.get('material'), len(m.get('uvs') or []), sorted(k for k in m if 'uv' in k.lower())] for m in scene['meshes']]
    for key, material in list(scene['materials'].items()) + list(scene.get('native_materials', {}).items()):
        text = json.dumps(material, default=str)
        found.setdefault('has_image', {})[key] = ['checks.png' in text, sorted(material)[:14] if isinstance(material, dict) else str(type(material))]
    result[name] = found


def spread(view):
    """How much the picture's middle varies: a chequered ball varies a great deal, a plain one hardly."""
    image = view.image
    values = [QtGui.QColor(image.pixel(int(image.width() * (.8 + .18 * i / 15)), int(image.height() * (.3 + .4 * j / 15)))).red() for i in range(16) for j in range(16)]
    return max(values) - min(values)


try:
    from moonray_modo import graph_images, material_override, materials, properties
    picture = QtGui.QImage(256, 256, QtGui.QImage.Format_RGB32)
    for y in range(256):
        for x in range(256):
            picture.setPixel(x, y, QtGui.qRgb(230, 60, 40) if (x // 32 + y // 32) % 2 else QtGui.qRgb(30, 60, 220))
    picture.save(str(out / 'checks.png'))
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    for key, value in dict(cenY=.6, sizeX=.5, sizeY=.5, sizeZ=.5).items():
        lx.eval('tool.attr prim.sphere %s %s' % (key, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    scene = modo.Scene()
    ball = scene.selected[0]
    ball.name = 'Ball'
    held['ball'] = ball
    # As an imported mesh has it: its UV map is not called Texture.
    with ball.geometry as geometry:
        geometry.vmaps.uvMaps[0].name = 'cheetah_UV'
    result['uv_maps'] = [m.name for m in ball.geometry.vmaps.uvMaps]
    materials.assign('DwaBaseMaterial', name='Body', color=[.8, .8, .8])
    material = next(item for item in scene.items('advancedMaterial') if properties.read(item).get('native_shader') == 'DwaBaseMaterial')
    held['material'] = material
    # As the imported scene has it: the mesh is inside a group folder, and it is the folder a group is tied to.
    folder = scene.addItem('groupLocator', name='Creature')
    ball.setParent(folder)
    held['folder'] = folder
    # The material's group goes inside a group tied to the ball itself.
    inner = held['material'].parent
    lx.eval('select.drop item')
    lx.eval('shader.create mask')
    outer = scene.selected[0]
    lx.eval('mask.setMesh {%s}' % held['folder'].name)
    result['outer_targets'] = [target.name for target in outer.itemGraph('shadeLoc').forward()]
    lx.eval('select.item {%s} set' % inner.id)
    lx.eval('texture.parent {%s} 0' % outer.id)
    result['tree'] = [[item.name, item.type, item.parent.name if item.parent else None] for item in (outer, inner, held['material'])]
    camera = scene.renderCamera
    camera.position.set((0.0, .6, 2.6))
    camera.rotation.set((0.0, 0.0, 0.0))
    taken('plain')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def render(then, wait=25000):
    try:
        panel = panel_widget()
        held.setdefault('stored', panel.preferences.store.value('runtime', ''))
        held.setdefault('engine', panel.preview_engine.currentData())
        panel.preferences.set('runtime', str(root / 'runtime/steady-0350-pool'))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
        QtWidgets.QApplication.processEvents()
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.start.click()
    except Exception:
        result['render_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(wait, then)


def first():
    render(nest)


def nest():
    try:
        panel = panel_widget()
        result['plain_picture'] = [panel.status.text(), spread(panel.preview), panel.warnings.toPlainText()[:300]]
        panel.window().grab().save(str(out / 'plain.png'))
        # The image is chosen now, with the preview following, as it is chosen in the properties.
        from moonray_modo import graph_images, material_override, properties
        material = held['material']
        # Written from inside a command, as the properties' popup writes it: a script run as one.
        (out / 'choose.json').write_text(json.dumps({'material': material.id, 'image': str(out / 'checks.png')}))
        lx.eval('@{%s}' % (root / 'tools/choose_albedo_image.py'))
        result['image_now'] = graph_images.image(properties.read(material), 'albedo')
        taken('nested')
    except Exception:
        result['nest_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(25000, last)


def last():
    try:
        panel = panel_widget()
        result['nested_picture'] = [panel.status.text(), spread(panel.preview), panel.warnings.toPlainText()[:300]]
        panel.window().grab().save(str(out / 'nested.png'))
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        panel.preferences.store.setValue('runtime', held['stored'])
    except Exception:
        result['last_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(5000, first)
