# python
"""Isolated GUI test: how the graph editor feels to marquee. A DwaBaseMaterial graph, its node selected so its long property list is
showing; then mouse events sent to the canvas, each timed: the press on empty canvas, the moves across the node, the release; and a
click on a node. Says at how many pixels of drag the marquee first shows. Writes test-results/graph-marquee/report.json."""
import json
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/graph-marquee'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def ms(call):
    begun = time.perf_counter()
    call()
    return round((time.perf_counter() - begun) * 1000, 1)


def send(view, kind, point, button=QtCore.Qt.LeftButton, buttons=QtCore.Qt.LeftButton):
    place = QtCore.QPointF(point)
    target = view.viewport()
    event = QtGui.QMouseEvent(kind, place, place, QtCore.QPointF(target.mapToGlobal(point)), button, buttons, QtCore.Qt.NoModifier)
    QtWidgets.QApplication.sendEvent(target, event)


def filled(editor, app):
    """Runs the window until the list of properties is done: how long that took, and the longest the window was held at once."""
    begun = time.perf_counter()
    longest = 0.0
    while time.perf_counter() - begun < 8 and (editor.inspect_waiting or editor.fill_job is not None):
        longest = max(longest, ms(app.processEvents))
    return {'total ms': round((time.perf_counter() - begun) * 1000), 'longest hold ms': longest, 'rows': editor.table.rowCount()}


def showing(view):
    band = getattr(view, 'band', None)
    if band is not None:
        return band.isVisible()
    return not view.rubberBandRect().isNull()


def run():
    try:
        editor = held['editor']
        view = editor.view
        app = QtWidgets.QApplication.instance()
        app.processEvents()
        node = editor.items['surface']
        result['nodes'] = len(editor.items)
        result['inspect ms, by itself'] = [ms(editor.inspect) for _ in range(3)]
        node.setSelected(True)
        app.processEvents()
        result['rows when selected'] = editor.table.rowCount()
        body = view.mapFromScene(node.sceneBoundingRect().center())
        result['drag distance Qt asks'] = QtWidgets.QApplication.startDragDistance()
        # Empty canvas, up and to the left of the node.
        corner = view.mapFromScene(node.sceneBoundingRect().topLeft()) - QtCore.QPoint(40, 40)
        result['canvas point holds nothing'] = view.itemAt(corner) is None
        result['press ms (a node selected, empty canvas)'] = ms(lambda: send(view, QtCore.QEvent.MouseButtonPress, corner))
        app.processEvents()
        first = None
        moves = []
        for step in range(1, 41):
            point = corner + QtCore.QPoint(step * 3, step * 3)
            moves.append(ms(lambda: send(view, QtCore.QEvent.MouseMove, point, QtCore.Qt.NoButton)))
            app.processEvents()
            if first is None and showing(view):
                first = (corner - point).manhattanLength()
        result['marquee first shows at pixels'] = first
        result['slowest move ms'] = max(moves)
        result['moves over 16 ms'] = sum(1 for value in moves if value > 16)
        result['selected while dragging'] = editor.selected_nodes()
        result['release ms'] = ms(lambda: send(view, QtCore.QEvent.MouseButtonRelease, corner + QtCore.QPoint(120, 120), QtCore.Qt.LeftButton, QtCore.Qt.NoButton))
        result['marquee gone after release'] = not showing(view)
        result['the list filling after the release'] = filled(editor, app)
        result['selected after'] = editor.selected_nodes()
        result['rows after'] = editor.table.rowCount()
        result['undo steps made by a marquee'] = len(editor.undo_states)
        # Empty canvas click clears the selection.
        send(view, QtCore.QEvent.MouseButtonPress, corner)
        send(view, QtCore.QEvent.MouseButtonRelease, corner, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
        app.processEvents()
        filled(editor, app)
        result['a click on empty canvas leaves selected'] = editor.selected_nodes()
        result['rows with nothing selected'] = editor.table.rowCount()
        # Clicked away with the list part filled: nothing of the node's is left, and the list ends empty.
        send(view, QtCore.QEvent.MouseButtonPress, body)
        send(view, QtCore.QEvent.MouseButtonRelease, body, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
        for _ in range(4000):
            app.processEvents()
            if 0 < editor.table.rowCount() < 60:
                break
        result['rows when clicked away'] = editor.table.rowCount()
        send(view, QtCore.QEvent.MouseButtonPress, corner)
        send(view, QtCore.QEvent.MouseButtonRelease, corner, QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
        filled(editor, app)
        result['rows after clicking away'] = editor.table.rowCount()
        # A click on the node.
        result['press ms on a node'] = ms(lambda: send(view, QtCore.QEvent.MouseButtonPress, body))
        result['release ms on a node'] = ms(lambda: send(view, QtCore.QEvent.MouseButtonRelease, body, QtCore.Qt.LeftButton, QtCore.Qt.NoButton))
        result['the list filling after the click'] = filled(editor, app)
        result['a click selects'] = editor.selected_nodes()
        result['rows after the click'] = editor.table.rowCount()
        before = list(node.pos().toTuple())
        # A drag moves it, one undo step.
        steps = len(editor.undo_states)
        send(view, QtCore.QEvent.MouseButtonPress, body)
        for step in range(1, 11):
            send(view, QtCore.QEvent.MouseMove, body + QtCore.QPoint(step * 8, 0), QtCore.Qt.NoButton)
        send(view, QtCore.QEvent.MouseButtonRelease, body + QtCore.QPoint(80, 0), QtCore.Qt.LeftButton, QtCore.Qt.NoButton)
        app.processEvents()
        result['a drag moved the node'] = list(node.pos().toTuple()) != before
        result['undo steps made by a move'] = len(editor.undo_states) - steps
        result['filling the list, ms'] = [ms(editor.inspect) for _ in range(4)]
        result['filling and drawing the list, ms'] = ms(lambda: (editor.inspect(), app.processEvents()))
        # Where the time of filling the list goes.
        import cProfile
        import io
        import pstats
        profile = cProfile.Profile()
        profile.enable()
        editor.inspect()
        profile.disable()
        text = io.StringIO()
        pstats.Stats(profile, stream=text).sort_stats('tottime').print_stats(22)
        (out / 'inspect-profile.txt').write_text(text.getvalue(), encoding='utf-8')
        result['done'] = True
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(200, lambda: lx.eval('!app.quit'))


try:
    from moonray_modo import nodes, properties
    from moonray_modo.node_editor import Editor
    item = modo.Scene().addMaterial(name='Marquee test')
    properties.write(item, {'node_graph': nodes.new(), 'node_override': True})
    editor = Editor(item)
    held['editor'] = editor
    editor.show()
    QtCore.QTimer.singleShot(1500, run)
except Exception:
    result['error'] = traceback.format_exc()
    save()
