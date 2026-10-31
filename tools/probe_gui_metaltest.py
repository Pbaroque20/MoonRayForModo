# python
"""Isolated GUI test: a copy of the user's metaltest.lxo (MOONRAY_PROBE_SCENE), its material selected. The form and the graph editor's
numbers side by side, and the scene as snapshot.pickle for rendering outside Modo. Writes test-results/metaltest/."""
import json
import os
import pathlib
import pickle
import sys
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/metaltest'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    from moonray_modo import host, properties
    lx.eval('!scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    scene = modo.Scene()
    material = next(m for m in scene.items('advancedMaterial') if properties.read(m).get('native_shader') == 'DwaMetalMaterial')
    held['item'] = material
    lx.eval('select.item {%s} set' % material.id)
    settings = properties.read(material)
    result['stored metallic_color'] = settings['native_parameters'].get('metallic_color')
    snapshot = host.snapshot()
    result['meshes'] = [(m.get('name'), 'ref_P' in (m.get('point_attributes') or {})) for m in snapshot.get('meshes', [])]
    (out / 'snapshot.pickle').write_bytes(pickle.dumps(snapshot, protocol=4))
except Exception:
    result['error'] = traceback.format_exc()
save()


def editor_open():
    try:
        from moonray_modo.node_editor import open_editor
        editor = held['editor'] = open_editor(held['item'])
        editor.show()
        QtCore.QTimer.singleShot(2500, measure)
    except Exception:
        result['open-error'] = traceback.format_exc()
        result['done'] = True
        save()


def measure():
    try:
        from moonray_modo.node_widgets import VectorField
        editor = held['editor']
        identity = editor.graph['root']
        editor.items[identity].setSelected(True)
        editor.inspect()
        fields = {f.key: [round(s.value(), 3) for s in f.spins] for f in editor.table.findChildren(VectorField) if f.is_color}
        result['graph editor colours'] = {key: fields.get(key) for key in ('metallic_color', 'metallic_edge_color', 'glitter_color_A')}
        sizes = {}
        for row in range(editor.table.rowCount()):
            label = editor.table.item(row, 0)
            key = (label.data(QtCore.Qt.UserRole) or label.text()) if label else ''
            if key in ('glitter_size_A', 'glitter_size_B'):
                widget = editor.table.cellWidget(row, 1)
                sizes[key] = widget.value() if hasattr(widget, 'value') else (editor.table.item(row, 1).text() if editor.table.item(row, 1) else None)
        result['graph editor flake sizes'] = sizes
        editor.grab().save(str(out / 'graph-editor.png'))
    except Exception:
        result['measure-error'] = traceback.format_exc()
    result['done'] = True
    save()


sys._probe_step = editor_open
QtCore.QTimer.singleShot(2500, editor_open)
