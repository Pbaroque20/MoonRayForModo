# python
"""Isolated GUI test: a scene whose graph has two material outputs (MOONRAY_PROBE_LXO, the tester's dragon_test.lxo).
The graph editor's list of networks is written down, then, as the tester did: the editor opened on the first material,
closed; opened on the second; the first chosen from its list. Each step is written down before the next, so that where
Modo goes down is known. Writes test-results/graph-switch/report.json and pictures."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/graph-switch'
out.mkdir(parents=True, exist_ok=True)
source = os.environ.get('MOONRAY_PROBE_LXO', r'C:\Users\Raphael Tobar\Downloads\dragon_test.lxo')
result = {'scene': source, 'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def step(name, **facts):
    result['steps'].append(dict(step=name, **facts))
    save()


def describe(item):
    from moonray_modo import properties
    data = properties.read(item)
    graph = data.get('node_graph') or {}
    nodes_ = graph.get('nodes') or {}
    return {'id': item.id, 'name': item.name, 'type': item.type, 'root': graph.get('root'),
            'displacement': graph.get('displacement'), 'nodes': len(nodes_),
            'materials_in_graph': sorted(k for k, v in nodes_.items() if 'Material' in str(v.get('type', ''))),
            'node_override': data.get('node_override'), 'native_shader': data.get('native_shader')}


def editors():
    from moonray_modo.node_editor import Editor
    from shiboken2 import isValid
    return [w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, Editor) and isValid(w) and w.isVisible()]


def begin():
    try:
        from moonray_modo.node_editor import graph_materials
        entries = graph_materials()
        held['entries'] = entries
        step('listed', networks=[[label, describe(item)] for label, item in entries])
        if len(entries) < 2:
            step('fewer than two networks: nothing to switch between');QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'));return
        from moonray_modo.node_editor import open_editor
        editor = open_editor(entries[0][1])
        step('opened first', title=editor.windowTitle(), picker=[editor.material_picker.itemText(i) for i in range(editor.material_picker.count())])
        editor.grab().save(str(out / '1-first.png'))
        QtCore.QTimer.singleShot(1500, close_first)
    except Exception:
        step('begin failed', error=traceback.format_exc())


def close_first():
    try:
        for editor in editors():editor.reject()
        step('closed first', open=len(editors()))
        QtCore.QTimer.singleShot(1500, open_second)
    except Exception:
        step('close failed', error=traceback.format_exc())


def open_second():
    try:
        from moonray_modo.node_editor import open_editor
        second = held['entries'][1][1]
        lx.eval('select.item {%s} set' % second.id)
        editor = open_editor(second)
        step('opened second', title=editor.windowTitle(), picker=[editor.material_picker.itemText(i) for i in range(editor.material_picker.count())])
        editor.grab().save(str(out / '2-second.png'))
        QtCore.QTimer.singleShot(1500, switch_back)
    except Exception:
        step('open second failed', error=traceback.format_exc())


def switch_back():
    try:
        editor = editors()[0]
        first = held['entries'][0][1]
        index = editor.material_picker.findData(first.id)
        step('switching back', index=index)
        editor.material_picker.setCurrentIndex(index)
        editor.switch_material(index)
        step('switch called')
        QtCore.QTimer.singleShot(2500, after_switch)
    except Exception:
        step('switch failed', error=traceback.format_exc())


def after_switch():
    try:
        shown = editors()
        step('after switch', open=[w.windowTitle() for w in shown])
        if shown:shown[0].grab().save(str(out / '3-switched.png'))
    except Exception:
        step('after switch failed', error=traceback.format_exc())
    QtCore.QTimer.singleShot(1000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('scene.open {%s} normal' % source)
    step('scene opened')
except Exception:
    step('open failed', error=traceback.format_exc())
QtCore.QTimer.singleShot(15000, begin)
