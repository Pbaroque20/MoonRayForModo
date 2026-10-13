# python
"""Isolated GUI test: a picture of the compositor's editor for the documents.

Two balls are rendered with MoonRay. The editor is opened and a graph made in it as it is made by hand, each node added
with the one before it selected: the beauty graded, given a vignette and sharpened. The library's long list of buffers
is folded so that the nodes there are to add are seen, the vignette is selected so that its settings show, and the
editor is pictured."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/compositor-picture'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def render():
    try:
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(45000, build)


def build():
    try:
        panel = panel_widget()
        panel.open_compositor()
        from moonray_modo import compositor_editor
        editor = held['editor'] = compositor_editor._open.get('editor')
        last = 'beauty'
        for kind in ('grade', 'vignette', 'sharpen'):
            editor.canvas.clearSelection()
            editor.items[last].setSelected(True)
            editor.add(kind)
            last = editor.selected()
            held[kind] = last
        tree = editor.node_tree
        for index in range(tree.topLevelItemCount()):
            group = tree.topLevelItem(index)
            group.setExpanded(group.text(0) not in ('Buffers of the render', 'Merge'))
        editor.canvas.clearSelection()
        editor.items[held['vignette']].setSelected(True)
        editor.show_composite()
        # The whole graph in view.
        editor.frame(everything=True)
        result['nodes'] = sorted(node['type'] for node in editor.graph['nodes'].values())
    except Exception:
        result['error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(6000, shoot)


def shoot():
    try:
        editor = held['editor']
        editor.grab().save(str(out / 'editor.png'))
        panel_widget().preview.grab().save(str(out / 'composite.png'))
        result['status'] = panel_widget().status.text()
        result['buffer'] = panel_widget().buffer.currentData()
    except Exception:
        result['error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    lx.eval('!app.quit')


try:
    for x in (-.6, .6):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples 3')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(8000, render)
