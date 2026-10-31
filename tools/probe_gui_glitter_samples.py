# python
"""Isolated GUI test. Glitter turned on in a DwaMetalMaterial, the snapshot reusing the geometry as a material edit does: do its meshes
have rest positions? And the graph editor's Samples field: its width against its longest choice, with pictures of it closed and
open. Writes test-results/glitter-samples/."""
import json
import pathlib
import sys
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/glitter-samples'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def rest_counts(snapshot):
    return {m.get('name'): ('ref_P' in (m.get('point_attributes') or {})) for m in snapshot.get('meshes', [])}


try:
    from moonray_modo import host, properties
    lx.eval('scene.new')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaMetalMaterial', 'parameters': {}}))
    scene = modo.Scene()
    material = next(m for m in scene.items('advancedMaterial') if properties.read(m).get('native_shader') == 'DwaMetalMaterial')
    held['item'] = material
    first = host.snapshot()
    result['glitter off'] = rest_counts(first)
    settings = properties.read(material)
    settings.setdefault('native_parameters', {})['show_glitter'] = True
    lx.eval('moonray.material.applyGraph {%s} %s' % (material.id, properties.encode(settings)))
    second = host.snapshot(reuse_geometry=first, refresh_materials=True)
    result['glitter on, geometry reused'] = rest_counts(second)
    settings = properties.read(material)
    settings['native_parameters'].pop('show_glitter')
    lx.eval('moonray.material.applyGraph {%s} %s' % (material.id, properties.encode(settings)))
    third = host.snapshot(reuse_geometry=second, refresh_materials=True)
    result['glitter off again, geometry reused'] = rest_counts(third)
except Exception:
    result['error'] = traceback.format_exc()
save()


def editor_open():
    try:
        from moonray_modo.node_editor import open_editor
        editor = held['editor'] = open_editor(held['item'])
        QtCore.QTimer.singleShot(3000, measure)
    except Exception:
        result['open-error'] = traceback.format_exc()
        result['done'] = True
        save()


def measure():
    try:
        from moonray_modo.material_preview import Panel
        panel = held['editor'].findChild(Panel)
        box = panel.samples
        metrics = box.fontMetrics()
        result['samples'] = {'width': box.width(), 'minimum': box.minimumWidth(), 'font': box.font().toString(),
                             'text': {box.itemText(i): metrics.horizontalAdvance(box.itemText(i)) for i in range(box.count())},
                             'sheet': box.styleSheet()[:200], 'application_sheet': len(QtWidgets.QApplication.instance().styleSheet())}
        for i in range(box.count()):
            box.setCurrentIndex(i)
            box.grab().save(str(out / ('field-%d.png' % i)))
        box.setCurrentIndex(box.count() - 1)
        panel.grab().save(str(out / 'panel.png'))
        box.showPopup()
        QtCore.QTimer.singleShot(600, opened)
    except Exception:
        result['measure-error'] = traceback.format_exc()
        result['done'] = True
        save()


def opened():
    try:
        from moonray_modo.material_preview import Panel
        box = held['editor'].findChild(Panel).samples
        view = box.view()
        result['samples']['list width'] = view.width()
        view.window().grab().save(str(out / 'list.png'))
        box.hidePopup()
    except Exception:
        result['list-error'] = traceback.format_exc()
    result['done'] = True
    save()


sys._probe_step = editor_open
QtCore.QTimer.singleShot(2500, editor_open)
