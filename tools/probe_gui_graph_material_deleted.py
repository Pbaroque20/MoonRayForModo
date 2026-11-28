# python
"""Isolated GUI test: a DWA material made, its MoonShine graph editor open (window, then docked), and the material
deleted while it is open, as a tester did; then the same with the material's group (mask) deleted. Modo crashed so;
now the editor closes and Modo goes on. After each step the editors standing are listed with Python's errors.
Writes report.json to MOONRAY_PROBE_OUT (else test-results/graph-material-deleted); 'finished' true means Modo lived
to the end.

Controls: PROBE_NO_DOCK=1 stops after the window cases, PROBE_NO_EDITOR=1 opens no editor, PROBE_PLAIN=1 makes plain
Modo materials. Modo's exit code at the quit is not this probe's verdict: after any material is deleted with
texture.delete, the test Modo crashes as it quits (0xC0000005), with or without an editor, with plain Modo materials
and with the kit's native parts left out (--without-native --without-controller), in 0.5.6.3 too (2026-11-28)."""
import json
import os
import pathlib
import sys
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\graph-material-deleted')
out.mkdir(parents=True, exist_ok=True)
result = {'steps': [], 'errors': [], 'hook': [], 'finished': False}
held = {}
_hook = sys.excepthook


def hook(kind, value, trace):
    result['hook'].append(''.join(traceback.format_exception(kind, value, trace)))
    save()
    _hook(kind, value, trace)


sys.excepthook = hook


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def editors():
    from moonray_modo import node_editor
    from shiboken2 import isValid
    found = []
    for widget in QtWidgets.QApplication.allWidgets():
        if isinstance(widget, node_editor.Editor) and isValid(widget) and widget.isVisible():
            found.append({'title': widget.windowTitle(), 'docked': widget.host is not None})
    return found


def step(name):
    result['steps'].append({'step': name, 'editors': editors(), 'materials': [i.name for i in modo.Scene().items('advancedMaterial')]})
    save()


def later(call, ms=1500):
    def run():
        try:
            call()
        except Exception:
            result['errors'].append(traceback.format_exc())
            save()
            finish()
    QtCore.QTimer.singleShot(ms, run)


def finish():
    result['finished'] = True
    save()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


def dwa_material(name):
    from moonray_modo import properties
    scene = modo.Scene()
    cube = scene.addMesh(name + 'Cube')
    with cube.geometry as geometry:
        corners = [(x, y, z) for x in (-.5, .5) for y in (-.5, .5) for z in (-.5, .5)]
        points = [geometry.vertices.new(p) for p in corners]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geometry.polygons.new([points[i] for i in face])
    lx.eval('select.item {%s} set' % cube.id)
    lx.eval('poly.setMaterial %s' % name)
    mask = [i for i in scene.items('mask') if i.name.startswith(name)][0]
    lx.eval('select.item {%s} set' % mask.id)
    lx.eval('shader.create advancedMaterial')
    material = [i for i in scene.selected if i.type == 'advancedMaterial'][-1]
    material.name = name
    if os.environ.get('PROBE_PLAIN'):
        return material, mask
    settings = properties.read(material)
    settings.update(moonshine_override=True, native_shader='DwaBaseMaterial', shader='DwaBaseMaterial', native_parameters={})
    properties.write(material, settings)
    return material, mask


def delete(item):
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('!texture.delete')


def window_then_delete():
    material, _ = held['first']
    lx.eval('select.item {%s} set' % material.id)
    if not os.environ.get('PROBE_NO_EDITOR'):
        lx.eval('moonray.material.nodes')
    later(lambda: (step('window open on Deleted A'), delete(material), later(after_first, 2500)), 3000)


def after_first():
    step('Deleted A deleted')
    _, mask = held['second']
    material = held['second'][0]
    lx.eval('select.item {%s} set' % material.id)
    if not os.environ.get('PROBE_NO_EDITOR'):
        lx.eval('moonray.material.nodes')
    later(lambda: (step('window open on Deleted B'), delete(mask), later(after_second, 2500)), 3000)


def after_second():
    step('Deleted B group deleted')
    if os.environ.get('PROBE_NO_DOCK'):
        finish()
        return
    from moonray_modo import graph_dock
    material, _ = held['third']
    dock = held['dock'] = graph_dock.GraphDock()
    dock.resize(900, 600)
    dock.show()
    dock.show_material(material)
    later(lambda: (step('docked on Deleted C'), delete(material), later(after_third, 2500)), 3000)


def after_third():
    dock = held['dock']
    step('Deleted C deleted, docked')
    result['dock_placeholder'] = dock.placeholder.isVisible()
    result['dock_editor'] = dock.editor is not None
    try:
        lx.eval('!app.undo')
    except Exception:
        result['errors'].append('undo: ' + traceback.format_exc())
    def end():
        step('delete undone')
        # The probe's own dock, a Python window with no parent: destroyed before quitting, as the kit's are
        # (quit_release), or Qt destroys it after Python has gone and Modo crashes on the way out.
        dock.dispose()
        dock.close()
        dock.deleteLater()
        held.clear()
        finish()
    later(end, 2500)


try:
    lx.eval('scene.new')
    held['first'] = dwa_material('DeletedA')
    held['second'] = dwa_material('DeletedB')
    held['third'] = dwa_material('DeletedC')
    save()
    later(window_then_delete, 2000)
except Exception:
    result['errors'].append(traceback.format_exc())
    save()
    lx.eval('!app.quit')
