# python
"""Isolated GUI test: removing node networks in the graph editor, on the tester's dragon_test.lxo (MOONRAY_PROBE_LXO).

The refractive material's graph holds a DwaBaseMaterial ('surface') beside its output: that loose network is offered and
removed, the output never. Then the other material's whole network is removed from the Graph menu (the confirmation and
the choice answered here), leaving the scene one network, when removing is refused; and Modo's undo brings it back.
Writes test-results/remove-network/report.json and pictures."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/remove-network'
out.mkdir(parents=True, exist_ok=True)
source = os.environ.get('MOONRAY_PROBE_LXO', r'C:\Users\Raphael Tobar\Downloads\dragon_test.lxo')
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def step(name, **facts):
    result['steps'].append(dict(step=name, **facts));save()


def networks():
    from moonray_modo.node_editor import graph_materials
    return [label for label, _ in graph_materials()]


def begin():
    try:
        from moonray_modo.node_editor import graph_materials, open_editor
        # The confirmations and the choice answered as a person would: yes, and the first entry offered.
        QtWidgets.QMessageBox.question = staticmethod(lambda *a, **k: QtWidgets.QMessageBox.Yes)
        QtWidgets.QInputDialog.getItem = staticmethod(lambda parent, title, text, items, *a, **k: (items[0], True))
        entries = graph_materials()
        refractive = next(item for label, item in entries if 'Refractive' in label)
        editor = held['editor'] = open_editor(refractive)
        graph = editor.graph
        others = sorted(n for n in graph['nodes'] if n != graph['root'])
        step('opened refractive', root=graph['root'], nodes={k: v['type'] for k, v in graph['nodes'].items()},
             used=sorted(editor.used_nodes()), loose={n: sorted(editor.loose_network(n) or []) for n in others},
             root_loose=editor.loose_network(graph['root']))
        editor.grab().save(str(out / '1-before.png'))
        loose = [n for n in others if editor.loose_network(n) and graph['nodes'][n]['type'].endswith('Material')]
        if loose:
            editor.remove_network(loose[0])
            QtWidgets.QApplication.processEvents()
        step('removed loose network', nodes={k: v['type'] for k, v in editor.graph['nodes'].items()}, info=editor.info.text())
        QtCore.QTimer.singleShot(1200, whole)
    except Exception:
        step('begin failed', error=traceback.format_exc())


def whole():
    try:
        from moonray_modo import properties
        editor = held['editor']
        stored = properties.read(editor.item)['node_graph']
        step('stored after loose removal', nodes=sorted(stored['nodes']))
        before = networks()
        editor.remove_material_network()
        after = networks()
        step('removed other network', before=before, after=after, picker=[editor.material_picker.itemText(i) for i in range(editor.material_picker.count())],
             info=editor.info.text())
        # One network left: refused.
        editor.remove_material_network()
        step('second removal with one network', info=editor.info.text(), networks=networks())
        editor.grab().save(str(out / '2-after.png'))
        lx.eval('app.undo')
        step('after undo', networks=networks())
    except Exception:
        step('whole failed', error=traceback.format_exc())
    QtCore.QTimer.singleShot(1000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('scene.open {%s} normal' % source)
    step('scene opened')
except Exception:
    step('open failed', error=traceback.format_exc())
QtCore.QTimer.singleShot(15000, begin)
