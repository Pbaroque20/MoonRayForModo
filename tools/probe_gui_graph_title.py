# python
"""Isolated GUI test: the MoonShine graph editor's title follows the material's name. A cube and a MoonShine material
named Original; the graph editor opened on it (node_editor.open_editor); the material renamed Test in Modo (item.name)
while the editor is open; its title read before and after. Each step on a timer, Modo's own events run between them.
Writes test-results/graph-title/report.json."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\graph-title')
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def later(call, ms=1500):
    def run():
        try:
            call()
        except Exception:
            result.setdefault('errors', []).append(traceback.format_exc())
            save()
            close_and_quit()
    QtCore.QTimer.singleShot(ms, run)


def close_and_quit():
    editor = held.get('editor')
    if editor is not None:
        try:
            editor.close()
        except Exception:
            pass
    save()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


def open_it():
    from moonray_modo import node_editor
    held['editor'] = editor = node_editor.open_editor(held['material'])
    result['title before'] = editor.windowTitle()
    later(rename, 1500)


def rename():
    lx.eval('select.item {%s} set' % held['material'].id)
    lx.eval('item.name {Test} advancedMaterial')
    result['name in Modo'] = modo.Scene().item(held['material'].id).name
    later(look, 2500)


def look():
    result['title after'] = held['editor'].windowTitle()
    result['follows'] = result['title after'].endswith('- Test')
    close_and_quit()


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    cube = scene.addMesh('Cube')
    with cube.geometry as geometry:
        corners = [(x, y, z) for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)]
        points = [geometry.vertices.new(p) for p in corners]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geometry.polygons.new([points[i] for i in face])
    lx.eval('select.item {%s} set' % cube.id)
    from moonray_modo import materials
    made = materials.assign('DwaBaseMaterial', name='Original')
    material = modo.Item(made) if made is not None and not isinstance(made, modo.Item) else made
    if material is None:
        material = [i for i in scene.items('advancedMaterial') if i.name != 'Base Material'][-1]
    lx.eval('select.item {%s} set' % material.id)
    lx.eval('item.name {Original} advancedMaterial')
    held['material'] = material
    result['material'] = material.name
    save()
    later(open_it, 2000)
except Exception:
    result['error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')
