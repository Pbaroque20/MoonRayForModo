# python
"""Isolated GUI test: a compositor node held and moved stays where it is moved.

A Grade is added to the compositor's graph and written to the scene. Then it is moved as a drag moves it: the button
held (what the canvas notes when it goes down), the node moved, and held there for longer than the editor takes to look
at the scene again. Where it is is noted while held, and after the button is let go and the move is written."""
import copy
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/compositor-drag'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def place(editor, identity):
    item = editor.items[identity]
    return [round(item.pos().x()), round(item.pos().y())]


def build():
    from moonray_modo import compositor_editor
    panel = panel_widget()
    panel.open_compositor()
    editor = compositor_editor._open.get('editor')
    held['editor'] = editor
    before = set(editor.graph['nodes'])
    editor.add('grade', QtCore.QPointF(100, 100), (editor.graph['root'], 'image'))
    held['grade'] = next(n for n in editor.graph['nodes'] if n not in before)
    editor.write()


def press_and_move():
    editor = held['editor']
    result['written_before'] = place(editor, held['grade'])
    editor.view.move_before = copy.deepcopy(editor.graph)
    item = editor.items[held['grade']]
    item.setSelected(True)
    item.setPos(item.pos() + QtCore.QPointF(300, 160))
    result['moved_to'] = place(editor, held['grade'])


def while_held():
    result['after_held_2s'] = place(held['editor'], held['grade'])


def let_go():
    editor = held['editor']
    editor.snap_selected()
    editor.remember(editor.view.move_before)
    editor.view.move_before = None


def after():
    editor = held['editor']
    result['after_let_go_2s'] = place(editor, held['grade'])
    stored = editor.stored() or {}
    result['scene_has'] = [round(v) for v in stored.get('nodes', {}).get(held['grade'], {}).get('position', [0, 0])]
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
QtCore.QTimer.singleShot(8000, lambda: run([(build, 2000), (press_and_move, 2200), (while_held, 100), (let_go, 2500), (after, 200)]))
