# python
"""Pictures for the docs: the graph editor's right side, a material's properties in their groups above the MoonRay
Widget's finished picture of it.

An orange DwaBaseMaterial is opened in the graph editor and its node selected. Every group but Diffuse is
folded for the picture, and the folds as they were are put back after. Once the widget has rendered, the right side is
pictured to docs/images/graph-editor-widget.png."""
import json
import traceback
from pathlib import Path
import lx
import modo
from PySide2 import QtCore, QtWidgets

ROOT = Path('C:/Users/Raphael Tobar/MoonRayForModo')
RUNTIME = 'C:/Users/Raphael Tobar/AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
out = ROOT / 'test-results/widget-doc'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}
SHOWN = ('Diffuse',)


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def editor():
    from moonray_modo.node_editor import Editor
    return next(w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, Editor) and w.isVisible())


def arrange():
    try:
        e = held['editor'] = editor()
        e.resize(1500, 1300)
        e.items['surface'].setSelected(True)
        QtWidgets.QApplication.processEvents()
        side = e.table
        while not (isinstance(side, QtWidgets.QSplitter) and side.orientation() == QtCore.Qt.Vertical):
            side = side.parentWidget()
        side.setSizes([760, 540])
        settings = QtCore.QSettings('MoonRayForModo', 'GraphEditor')
        key = 'folded/' + e.graph['nodes']['surface']['type']
        held['key'], held['before'] = key, settings.value(key, None)
        groups = list(dict.fromkeys(e.group_rows.values()))
        result['groups'] = groups
        settings.setValue(key, '|'.join(sorted(g for g in groups if g not in SHOWN)))
        e.filter_properties()
        e.material_preview.renderer.finished.connect(lambda *_: QtCore.QTimer.singleShot(1500, picture))
        QtCore.QTimer.singleShot(60000, picture)
    except Exception:
        result['error'] = traceback.format_exc(); restore(); save(); lx.eval('!app.quit')


def restore():
    if 'key' not in held:return
    settings = QtCore.QSettings('MoonRayForModo', 'GraphEditor')
    if held['before'] is None:settings.remove(held['key'])
    else:settings.setValue(held['key'], held['before'])


def picture():
    if held.get('done'):return
    held['done'] = True
    try:
        e = held['editor']
        side = e.table
        while side is not None and not (isinstance(side, QtWidgets.QSplitter) and side.orientation() == QtCore.Qt.Vertical):
            side = side.parentWidget()
        result['status'] = e.material_preview.status.text()
        side.grab().save(str(ROOT / 'docs/images/graph-editor-widget.png'))
        e.grab().save(str(out / 'editor.png'))
    except Exception:
        result['error'] = traceback.format_exc()
    restore()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


try:
    from moonray_modo import native, nodes, properties
    native.default_runtime = lambda: RUNTIME
    item = modo.Scene().addMaterial(name='Orange')
    properties.write(item, {'node_graph': nodes.new(parameters={'albedo': [0.8, 0.3, 0.06], 'roughness': 0.25}),
                            'node_override': True})
    modo.Scene().select(item)
    lx.eval('moonray.material.nodes')
    QtCore.QTimer.singleShot(1500, arrange)
except Exception:
    result['error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')
