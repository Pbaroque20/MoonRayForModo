# python
"""Isolated GUI test: the ways a MoonShine graph editor is opened, on a material whose albedo and roughness are UDIM
sets (as the form's image fields write them) beside a new material with none, under one mask with a Modo material
(a tester's Shader Tree). Steps, each on a timer: the form's Open Graph Editor command (moonray.material.nodes) on the
textured material; the editor on the new one, then the textured one chosen in its material list (switch_material);
the scene saved, closed and opened again, and the command once more. After each, the editors standing are listed
(windows that are visible, where, minimised or not) with anything said in the diagnostics and Python's errors.
Writes report.json to MOONRAY_PROBE_OUT (else test-results/graph-open-paths)."""
import json
import os
import pathlib
import sys
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\graph-open-paths')
out.mkdir(parents=True, exist_ok=True)
tiles = out / 'tiles'
tiles.mkdir(exist_ok=True)
result = {'steps': [], 'errors': [], 'hook': []}
held = {}
_hook = sys.excepthook


def hook(kind, value, trace):
    result['hook'].append(''.join(traceback.format_exception(kind, value, trace)))
    save()
    _hook(kind, value, trace)


sys.excepthook = hook


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def tile(name, colour, size=1024, deep=False):
    image = QtGui.QImage(size, size, QtGui.QImage.Format_RGBA64 if deep else QtGui.QImage.Format_RGB888)
    image.fill(QtGui.QColor(*colour))
    image.save(str(tiles / name))


def editors():
    from moonray_modo import node_editor
    found = []
    for widget in QtWidgets.QApplication.topLevelWidgets() + [w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, node_editor.Editor)]:
        if isinstance(widget, node_editor.Editor) and widget not in [f[0] for f in found]:
            found.append((widget, {'title': widget.windowTitle(), 'visible': widget.isVisible(), 'minimised': widget.isMinimized(),
                                   'geometry': widget.geometry().getRect(), 'host': widget.host is not None}))
    return [f[1] for f in found]


def step(name):
    result['steps'].append({'step': name, 'editors': editors(), 'open': [str(k) for k in __import__('moonray_modo.node_editor', fromlist=['_open'])._open]})
    save()


def later(call, ms=1500):
    def run():
        try:
            call()
        except Exception:
            result['errors'].append(traceback.format_exc())
            save()
            close_and_quit()
    QtCore.QTimer.singleShot(ms, run)


def close_and_quit():
    from moonray_modo import node_editor
    for editor in list(node_editor._open.values()):
        try:
            editor.close()
        except Exception:
            pass
    save()
    QtCore.QTimer.singleShot(2500, lambda: lx.eval('!app.quit'))


def material_with(scene, mask, name, images):
    from moonray_modo import properties, graph_images, material_override
    lx.eval('select.item {%s} set' % mask.id)
    lx.eval('shader.create advancedMaterial')
    material = [i for i in scene.selected if i.type == 'advancedMaterial'][-1]
    material.name = name
    settings = properties.read(material)
    settings.update(moonshine_override=True, native_shader='DwaBaseMaterial', shader='DwaBaseMaterial', native_parameters={})
    properties.write(material, settings)
    for key, path in images.items():
        settings = properties.read(material)
        graph = graph_images.set_image(settings, key, path)
        properties.write(material, material_override.synchronize(settings, graph))
    return material


def build():
    for number in (1001, 1002, 1011):
        tile('dr.%d.tif' % number, (180, 60 + number % 7 * 20, 40), deep=True)
        tile('rgh.%d.tif' % number, (128, 128, 128), deep=True)
    scene = modo.Scene()
    cube = scene.addMesh('Enterprise')
    with cube.geometry as geometry:
        corners = [(x, y, z) for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)]
        points = [geometry.vertices.new(p) for p in corners]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geometry.polygons.new([points[i] for i in face])
    lx.eval('select.item {%s} set' % cube.id)
    lx.eval('poly.setMaterial Enterprise')
    mask = [i for i in scene.items('mask') if i.name.startswith('Enterprise')][0]
    base = str(tiles).replace('\\', '/')
    held['existing'] = material_with(scene, mask, 'DwaBaseMaterial', {'albedo': base + '/dr.<UDIM>.tif', 'roughness': base + '/rgh.<UDIM>.tif'})
    held['new'] = material_with(scene, mask, 'DwaBaseMaterial (2)', {})
    from moonray_modo import properties
    result['graph'] = properties.read(held['existing']).get('node_graph')
    save()


def by_command():
    lx.eval('select.item {%s} set' % held['existing'].id)
    try:
        lx.eval('moonray.material.nodes')
    except Exception:
        result['errors'].append('command: ' + traceback.format_exc())
    later(lambda: (step('command on the textured material'), later(switch, 500)), 3000)


def switch():
    from moonray_modo import node_editor
    for editor in list(node_editor._open.values()):
        editor.close()
    held['editor'] = editor = node_editor.open_editor(held['new'])
    later(lambda: choose(editor), 3000)


def choose(editor):
    step('editor on the new material')
    index = editor.material_picker.findData(held['existing'].id)
    result['picker'] = [editor.material_picker.itemText(i) for i in range(editor.material_picker.count())]
    editor.material_picker.setCurrentIndex(index)
    editor.material_picker.activated.emit(index)
    later(lambda: (step('switched to the textured material'), later(reopen, 500)), 3000)


def reopen():
    from moonray_modo import node_editor
    for editor in list(node_editor._open.values()):
        editor.close()
    path = str(out / 'udim_scene.lxo')
    lx.eval('!scene.saveAs {%s} $LXOB false' % path)
    lx.eval('!scene.close')
    lx.eval('!scene.open {%s} normal' % path)
    scene = modo.Scene()
    held['existing'] = [i for i in scene.items('advancedMaterial') if i.name == 'DwaBaseMaterial'][0]
    lx.eval('select.item {%s} set' % held['existing'].id)
    try:
        lx.eval('moonray.material.nodes')
    except Exception:
        result['errors'].append('command after reopen: ' + traceback.format_exc())
    later(lambda: (step('command after the scene was opened again'), close_and_quit()), 3000)


try:
    lx.eval('scene.new')
    build()
    later(by_command, 2000)
except Exception:
    result['errors'].append(traceback.format_exc())
    save()
    lx.eval('!app.quit')
