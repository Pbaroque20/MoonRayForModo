# python
"""Isolated GUI test: a large MaterialX graph opens on its output at a readable size, and the wheel zooms it both ways.

PROBE_MTLX names the MaterialX file. The scale of the view is written down as the file is loaded, after wheel turns
towards the user from there, after the whole graph is framed, and after wheel turns in from that framing, which is
where the wheel used to do nothing."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/graph-zoom'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def wheel(view, steps):
    place = QtCore.QPointF(view.viewport().rect().center())
    for _ in range(abs(steps)):
        event = QtGui.QWheelEvent(place, view.viewport().mapToGlobal(place.toPoint()), QtCore.QPoint(0, 0), QtCore.QPoint(0, 120 if steps > 0 else -120),
                                  QtCore.Qt.NoButton, QtCore.Qt.NoModifier, QtCore.Qt.NoScrollPhase, False)
        view.wheelEvent(event)
    return round(view.transform().m11(), 4)


try:
    from moonray_modo import properties
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    held['item'] = modo.Scene().selected[0]
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        import copy
        from moonray_modo import materialx
        from moonray_modo.node_editor import open_editor
        editor = held['editor'] = open_editor(held['item'])
        result['small_graph_scale'] = round(editor.view.transform().m11(), 4)
        editor.graph = materialx.read(os.environ['PROBE_MTLX'])
        editor.rebuild()
        editor.frame_output()
        QtWidgets.QApplication.processEvents()
        result['nodes'] = len(editor.graph['nodes'])
        result['opened_at'] = round(editor.view.transform().m11(), 4)
        shown = editor.view.mapToScene(editor.view.viewport().rect()).boundingRect()
        result['output_in_view'] = shown.contains(editor.items[editor.graph['root']].sceneBoundingRect().center())
        editor.grab().save(str(out / 'opened.png'))
        result['out_from_opening'] = wheel(editor.view, -6)
        editor.frame(everything=True)
        result['framed_all'] = round(editor.view.transform().m11(), 4)
        result['in_from_framed'] = wheel(editor.view, 8)
        editor.grab().save(str(out / 'zoomed_in.png'))
        result['in_as_far_as_it_goes'] = wheel(editor.view, 40)
        result['out_as_far_as_it_goes'] = wheel(editor.view, -80)
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(800, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(2500, step2)
