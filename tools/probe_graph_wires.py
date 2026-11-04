# python
"""GUI test of a tester's stale wire: a DwaBaseMaterial's albedo wired from an ImageMap, a DwaRefractiveMaterial added
unwired, then the ImageMap node moved (by setPos, then by a mouse drag in the view). After each move, where its wire
starts against where its output socket is, and the editor's busy and rebuilding flags; the diagnostics' lines. Writes
test-results/graph-wires/report.json and pictures."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\graph-wires')
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def wire_report(label):
    editor = held['editor']
    image = held['image']
    socket = editor.items[image].sockets[None].scenePos()
    starts = []
    for edge in editor.links:
        if getattr(edge, 'connection', None) and editor.graph['nodes'][edge.connection[0]].get('inputs', {}).get(edge.connection[1]) == image:
            p = edge.path().pointAtPercent(0.0)
            starts.append([round(p.x(), 1), round(p.y(), 1)])
    result[label] = {'socket': [round(socket.x(), 1), round(socket.y(), 1)], 'wire_starts': starts,
                     'busy': editor.busy, 'rebuilding': getattr(editor, 'rebuilding', None),
                     'stored_position': editor.graph['nodes'][image].get('position')}
    editor.grab().save(str(out / (label + '.png')))


try:
    from moonray_modo import properties
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.library.assign %s' % properties.encode({'shader': 'DwaBaseMaterial', 'parameters': {}}))
    held['item'] = modo.Scene().selected[0]
    result['item'] = [held['item'].name, held['item'].type]
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        from moonray_modo.node_editor import open_editor
        editor = held['editor'] = open_editor(held['item'])
        import os
        if os.environ.get('PROBE_WIDGET_MOONRAY'):
            # The widget on MoonRay, as before it was XPU2's: its session started again as MoonRay's.
            widget = editor.material_preview
            widget.renderer.session.always_xpu2 = False
            widget.renderer.session.stop()
            result['widget_moonray'] = True
        editor.resize(1400, 900)
        root_id = editor.graph['root']
        centre = editor.view.mapToScene(editor.view.viewport().rect().center())
        editor.add_at = QtCore.QPointF(centre.x() - 360, centre.y() - 120)
        editor.selected_input = (root_id, 'albedo')
        editor.kinds.setCurrentText('ImageMap')
        editor.add(connect=True)
        held['image'] = next(k for k, v in editor.graph['nodes'].items() if v['type'] == 'ImageMap')
        result['wired'] = editor.graph['nodes'][root_id].get('inputs')
        # The tester's step: a material node added, wired to nothing.
        editor.add_at = QtCore.QPointF(centre.x() - 200, centre.y() + 200)
        editor.selected_input = None
        editor.kinds.setCurrentText('DwaRefractiveMaterial')
        editor.add(connect=False)
        result['nodes'] = {k: v['type'] for k, v in editor.graph['nodes'].items()}
        editor.frame(everything=True)
        QtWidgets.QApplication.processEvents()
        wire_report('after_adding')
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1500, step3)


def step3():
    try:
        editor = held['editor']
        node = editor.items[held['image']]
        node.setPos(node.pos() + QtCore.QPointF(-120, 80))
        QtWidgets.QApplication.processEvents()
        wire_report('after_setpos')
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1500, step4)


def mouse(kind, viewport, point, buttons):
    from PySide2 import QtGui
    button = QtCore.Qt.LeftButton if kind != QtCore.QEvent.MouseMove else QtCore.Qt.NoButton
    event = QtGui.QMouseEvent(kind, QtCore.QPointF(point), button, buttons, QtCore.Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(viewport, event)
    QtWidgets.QApplication.processEvents()


def step4():
    try:
        editor = held['editor']
        node = editor.items[held['image']]
        # Pressed on the node's header and dragged, as a hand does: events sent to the view's viewport.
        grip = editor.view.mapFromScene(node.scenePos() + QtCore.QPointF(40, 10))
        viewport = editor.view.viewport()
        result['grip'] = [grip.x(), grip.y()]
        result['item_at_grip'] = type(editor.view.itemAt(grip)).__name__
        mouse(QtCore.QEvent.MouseButtonPress, viewport, grip, QtCore.Qt.LeftButton)
        for k in range(1, 11):
            mouse(QtCore.QEvent.MouseMove, viewport, grip + QtCore.QPoint(-8 * k, 6 * k), QtCore.Qt.LeftButton)
        wire_report('during_drag')
        mouse(QtCore.QEvent.MouseButtonRelease, viewport, grip + QtCore.QPoint(-80, 60), QtCore.Qt.NoButton)
        wire_report('after_drag')
    except Exception:
        result['step4_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2500, step4b)


def step4b():
    # After the release has written the material and the widget has rendered: the wire still where the node is?
    try:
        wire_report('after_drag_settled')
    except Exception:
        result['step4b_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, step5)


def step5():
    try:
        import glob, os
        logs = sorted(glob.glob(os.path.join(os.environ.get('LOCALAPPDATA', ''), 'MoonRayForModo', 'Diagnostics', 'material-preview-%d.log' % os.getpid())))
        result['diagnostics'] = pathlib.Path(logs[-1]).read_text(encoding='utf-8').splitlines()[-30:] if logs else []
    except Exception:
        result['step5_error'] = traceback.format_exc()
    save()
    # PROBE_CLOSE_FIRST: the editor (and its widget's session) closed before Modo quits.
    import os
    if os.environ.get('PROBE_CLOSE_FIRST'):
        held['editor'].close()
        QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
    else:
        QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(4000, step2)
