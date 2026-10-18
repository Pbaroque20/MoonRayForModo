# python
"""Isolated GUI test: the compositor's Colour node shows its colour as a chip, and a click on the chip chooses another.

A Colour node is added and pictured. Its chip is clicked, as the canvas passes a click to it, with the colour picker's
answer stood in for (an sRGB orange, 255 128 0); the colour the node keeps (linear), the chip's colour and the undo of
the change are noted, and the node pictured again."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/colour-chip'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def chip_of(editor, identity):
    from moonray_modo.compositor_editor import Swatch
    return next((item for item in editor.items[identity].childItems() if isinstance(item, Swatch)), None)


def build():
    from moonray_modo import compositor_editor
    panel = panel_widget()
    panel.open_compositor()
    editor = compositor_editor._open.get('editor')
    held['editor'] = editor
    before = set(editor.graph['nodes'])
    editor.add('constant', QtCore.QPointF(0, 150))
    held['node'] = next(n for n in editor.graph['nodes'] if n not in before)
    chip = chip_of(editor, held['node'])
    result['chip_before'] = chip.brush().color().name() if chip else None
    editor.frame(everything=True)
    QtWidgets.QApplication.processEvents()
    editor.grab().save(str(out / 'before.png'))


def click():
    editor = held['editor']
    # The colour picker answers with an orange.
    QtWidgets.QColorDialog.getColor = staticmethod(lambda *args, **kw: QtGui.QColor(255, 128, 0))
    chip = chip_of(editor, held['node'])
    event = QtWidgets.QGraphicsSceneMouseEvent(QtCore.QEvent.GraphicsSceneMouseRelease)
    event.setPos(chip.rect().center())
    event.setButton(QtCore.Qt.LeftButton)
    chip.mouseReleaseEvent(event)


def after():
    editor = held['editor']
    result['kept'] = editor.graph['nodes'][held['node']]['parameters'].get('color')
    chip = chip_of(editor, held['node'])
    result['chip_after'] = chip.brush().color().name() if chip else None
    QtWidgets.QApplication.processEvents()
    editor.grab().save(str(out / 'after.png'))
    editor.undo()
    result['after_undo'] = editor.graph['nodes'][held['node']]['parameters'].get('color')
    editor.close()


def run(steps, index=0):
    if index >= len(steps):
        save()
        lx.eval('!app.quit')
        return
    function, wait = steps[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    QtCore.QTimer.singleShot(wait, lambda: run(steps, index + 1))


try:
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run([(build, 1000), (click, 1000), (after, 300)]))
