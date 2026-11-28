# python
"""Isolated GUI test: the MoonShine graph editor opens on a DwaBaseMaterial whose albedo and roughness images were
chosen as UDIM sets in its form (graph_images.set_image, as the form's image fields do). Variants: a set from 1001, a
set that starts later (1002, 1003: no 1001), a pattern with no tiles at all. Each editor is opened with
node_editor.open_editor, its traceback kept; then a switch from one material to another in the editor's list.
Writes report.json to MOONRAY_PROBE_OUT (else test-results/graph-udim)."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\graph-udim')
out.mkdir(parents=True, exist_ok=True)
tiles = out / 'tiles'
tiles.mkdir(exist_ok=True)
result = {'opened': {}, 'errors': []}
held = {'editors': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def tile(name, colour):
    image = QtGui.QImage(64, 64, QtGui.QImage.Format_RGB888)
    image.fill(QtGui.QColor(*colour))
    image.save(str(tiles / name))


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
    for editor in held['editors']:
        try:
            editor.close()
        except Exception:
            pass
    save()
    QtCore.QTimer.singleShot(2500, lambda: lx.eval('!app.quit'))


def material_with(scene, name, images):
    from moonray_modo import materials, properties, graph_images, material_override
    made = materials.assign('DwaBaseMaterial', name=name)
    material = modo.Item(made) if made is not None and not isinstance(made, modo.Item) else made
    if material is None:
        material = scene.selected[-1]
    lx.eval('select.item {%s} set' % material.id)
    for key, path in images.items():
        settings = properties.read(material)
        graph = graph_images.set_image(settings, key, path)
        properties.write(material, material_override.synchronize(settings, graph))
    return material


def open_each():
    from moonray_modo import node_editor
    for name, material in held['materials']:
        lx.eval('select.item {%s} set' % material.id)
        try:
            editor = node_editor.open_editor(material)
            held['editors'].append(editor)
            result['opened'][name] = {'title': editor.windowTitle(), 'visible': editor.isVisible()}
        except Exception:
            result['opened'][name] = {'error': traceback.format_exc()}
        save()
    later(look, 6000)


def look():
    # The thumbnails as they stand once their pictures had time to come.
    for editor in held['editors']:
        try:
            if not editor.isVisible():
                continue
            words = {}
            for identity, node in editor.items.items():
                preview = getattr(node, 'preview', None)
                if preview is None:
                    continue
                words[identity] = preview.toPlainText() if hasattr(preview, 'toPlainText') else 'picture'
            result.setdefault('previews', {})[editor.windowTitle()] = words
            result.setdefault('labels', {})[editor.windowTitle()] = {
                identity: node.preview.toolTip() for identity, node in editor.items.items() if getattr(node, 'preview', None) is not None}
            editor.grab().save(str(out / (editor.windowTitle().split(' - ')[-1].replace(' ', '_') + '.png')))
        except Exception:
            result['errors'].append(traceback.format_exc())
    save()
    later(failing, 500)


def failing():
    """An editor that cannot be made: said in a message box (recorded here, not shown), and another material chosen in
    an open editor's list leaves that editor open."""
    from moonray_modo import node_editor
    from PySide2 import QtWidgets
    said = result['failure'] = {'boxes': []}
    QtWidgets.QMessageBox.exec_ = lambda box: said['boxes'].append(box.text()) or 0
    build = node_editor.Editor.build

    def broken(self, *args):
        raise RuntimeError('a probe failure')
    node_editor.Editor.build = broken
    plain = dict(held['materials'])['Plain']
    for editor in list(node_editor._open.values()):
        if editor.item.id == plain.id:
            editor.done(0)
    try:
        node_editor.open_editor(plain)
        said['open'] = 'opened (unexpected)'
    except node_editor.OpenFailed as exc:
        said['open'] = 'OpenFailed: ' + str(exc)
    standing = node_editor._open.get((dict(held['materials'])['From1001'].id, False))
    picker = standing.material_picker
    standing.switch_material(picker.findData(plain.id))
    node_editor.Editor.build = build

    def after():
        said['switching editor still open'] = standing.isVisible()
        said['info'] = standing.info.text()
        save()
        close_and_quit()
    later(after, 1500)


try:
    for number, colour in ((1001, (200, 40, 40)), (1002, (40, 200, 40))):
        tile('from1001_col.%d.tif' % number, colour)
        tile('from1001_rgh.%d.tif' % number, (128, 128, 128))
    for number, colour in ((1002, (40, 40, 200)), (1003, (200, 200, 40))):
        tile('later_col.%d.tif' % number, colour)
        tile('later_rgh.%d.tif' % number, (90, 90, 90))
    lx.eval('scene.new')
    scene = modo.Scene()
    cube = scene.addMesh('Cube')
    with cube.geometry as geometry:
        corners = [(x, y, z) for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)]
        points = [geometry.vertices.new(p) for p in corners]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geometry.polygons.new([points[i] for i in face])
    base = str(tiles).replace('\\', '/')
    held['materials'] = []
    for name, stem in (('From1001', 'from1001'), ('Later', 'later'), ('NoTiles', 'none')):
        lx.eval('select.item {%s} set' % cube.id)
        material = material_with(scene, name, {'albedo': base + '/%s_col.<UDIM>.tif' % stem,
                                               'roughness': base + '/%s_rgh.<UDIM>.tif' % stem})
        held['materials'].append((name, material))
    lx.eval('select.item {%s} set' % cube.id)
    held['materials'].append(('Plain', material_with(scene, 'Plain', {})))
    from moonray_modo import properties
    result['graphs'] = {name: properties.read(material).get('node_graph') for name, material in held['materials']}
    result['types'] = {name: material.type for name, material in held['materials']}
    save()
    later(open_each, 2000)
except Exception:
    result['errors'].append(traceback.format_exc())
    save()
    lx.eval('!app.quit')
