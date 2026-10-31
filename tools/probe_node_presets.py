# python
"""Isolated GUI test: the graph editor's Presets, with its dialogs answered: selected nodes saved and added to another
material with their wire; a whole network saved, added, and put in a graph's place; undo; delete. Presets go to a folder
of the test's. Writes test-results/node-presets/report.json."""
import json
import pathlib
import traceback
from unittest import mock
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/node-presets'
out.mkdir(parents=True, exist_ok=True)
folder = out / 'presets'
for old in folder.glob('*'):
    old.unlink()
image = str(root / 'downloads/moonray-example-scenes/scenes/bedroom/scene.png')
result = {'steps': []}


class Answer:
    """The Whole Network question, answered by the button of this text."""
    text = 'Add Its Nodes'

    def __init__(self, *args, **kw):
        self.buttons = {}
        self.chosen = None

    def addButton(self, *args):
        made = object()
        self.buttons[args[0] if isinstance(args[0], str) else 'Cancel'] = made
        return made

    def exec_(self):
        self.chosen = self.buttons.get(Answer.text)

    def clickedButton(self):
        return self.chosen


def note(name, editor):
    graph = editor.graph
    result['steps'].append({'step': name, 'nodes': sorted(n['type'] for n in graph['nodes'].values()), 'root': graph['nodes'].get(graph.get('root'), {}).get('type'),
                            'wires': sum(len(n.get('inputs') or {}) for n in graph['nodes'].values()), 'selected': len(editor.selected_nodes()),
                            'info': editor.info.text(), 'listed': [row[:2] for row in presets.listed()],
                            'stored_same': properties.read(editor.item).get('node_graph', {}).get('nodes', {}).keys() == graph['nodes'].keys()})
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    from moonray_modo import node_presets as presets, nodes, properties
    from moonray_modo.node_editor import Editor
    with mock.patch.object(presets, 'folder', lambda: folder), mock.patch.object(QtWidgets.QMessageBox, 'question', lambda *a, **k: QtWidgets.QMessageBox.Yes), \
            mock.patch.object(QtWidgets.QMessageBox, 'warning', lambda self, title, text: result.setdefault('warnings', []).append(str(text))):
        scene = modo.Scene()
        first = scene.addMaterial(name='First')
        second = scene.addMaterial(name='Second')
        made = nodes.new()
        made['nodes']['img'] = {'type': 'image', 'parameters': {'file': image, 'uv_map': ''}, 'inputs': {}, 'position': [-400, 0]}
        made['nodes']['hsv'] = {'type': 'ColorCorrectHsvMap', 'parameters': {}, 'inputs': {'input': 'img'}, 'position': [-100, 0]}
        made['nodes']['surface']['inputs']['albedo'] = 'hsv'
        lx.eval('moonray.material.applyGraph {%s} %s' % (first.id, properties.encode({'node_graph': nodes.validate(made), 'node_override': True})))
        lx.eval('moonray.material.applyGraph {%s} %s' % (second.id, properties.encode({'node_graph': nodes.new(), 'node_override': True})))
        editor = Editor(first)
        editor.show()
        QtWidgets.QApplication.processEvents()
        editor.canvas.clearSelection()
        editor.items['img'].setSelected(True)
        editor.items['hsv'].setSelected(True)
        with mock.patch.object(QtWidgets.QInputDialog, 'getText', lambda *a, **k: ('Graded image', True)):
            editor.save_preset(False)
        with mock.patch.object(QtWidgets.QInputDialog, 'getText', lambda *a, **k: ('Whole look', True)):
            editor.save_preset(True)
        note('first: both saved', editor)
        editor.close()

        other = Editor(second)
        other.show()
        QtWidgets.QApplication.processEvents()
        note('second, as it starts', other)
        with mock.patch.object(QtWidgets.QInputDialog, 'getItem', lambda self, title, label, items, *a: (next(i for i in items if i.startswith('Graded')), True)):
            other.load_preset()
        note('selected nodes added', other)
        other.undo()
        note('undone', other)
        with mock.patch.object(QtWidgets.QInputDialog, 'getItem', lambda self, title, label, items, *a: (next(i for i in items if i.startswith('Whole')), True)), \
                mock.patch.object(QtWidgets, 'QMessageBox', type('Box', (Answer,), {'Question': 0, 'AcceptRole': 0, 'Cancel': 0, 'Yes': 1, 'question': staticmethod(lambda *a, **k: 1), 'warning': staticmethod(lambda *a, **k: None)})):
            Answer.text = 'Add Its Nodes'
            other.load_preset()
            note('network added', other)
            other.undo()
            Answer.text = 'Replace This Graph'
            other.load_preset()
            note('network in the graph\'s place', other)
            with mock.patch.object(QtWidgets.QInputDialog, 'getItem', lambda self, title, label, items, *a: (next(i for i in items if i.startswith('Graded')), True)):
                other.delete_preset()
            note('one deleted', other)
        other.close()
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))
