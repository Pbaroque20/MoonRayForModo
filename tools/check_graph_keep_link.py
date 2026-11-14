"""The graph editor keeps a node's connection when a value is typed or dragged on the same input (a DwaMixMaterial's
Mix set to 0 with a map wired to it keeps the map, which gives the value); an override layer's own input for it is
still dropped, as the override then gives a value.

Run with Modo's Python as tools/check_colour_popup.py says (through the scratchpad qt_run wrapper for the DLL folders)."""
import copy
import pathlib
import sys
import types
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
for name in ('lx', 'lxu', 'lxu.command', 'lxu.object', 'lxu.select', 'lxifc', 'modo', 'modo.constants'):
    sys.modules.setdefault(name, mock.MagicMock())
from PySide2 import QtWidgets  # noqa: E402
app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
from moonray_modo.node_editor import Editor  # noqa: E402

failures = []
graph = {'version': 1, 'root': 'mix', 'nodes': {
    'mix': {'type': 'DwaMixMaterial', 'parameters': {}, 'inputs': {'mix': 'noise'}},
    'noise': {'type': 'NoiseMap', 'parameters': {}, 'inputs': {}}},
    'overrides': [{'node': 'mix', 'enabled': True, 'parameters': {}, 'inputs': {'mix': 'noise'}}]}
editor = types.SimpleNamespace(busy=False, graph=copy.deepcopy(graph), validate_draft=lambda: None,
                               remember=lambda before: None, selected=lambda: None)
editor.holds = lambda *a: Editor.holds(editor, *a)
editor.unlink_override = lambda *a: Editor.unlink_override(editor, *a)
try:
    Editor.set_value(editor, 'mix', 'mix', -1, 0.0)
except Exception as exc:  # what the stand-in lacks after the value is written does not matter here
    if editor.graph['nodes']['mix']['parameters'].get('mix') != 0.0:
        failures.append('set_value failed: %r' % exc)
node = editor.graph['nodes']['mix']
if node['parameters'].get('mix') != 0.0:
    failures.append('Mix was not set to 0: %s' % node['parameters'])
if node['inputs'].get('mix') != 'noise':
    failures.append('the connection to Mix was dropped')
layer = editor.graph['overrides'][0]
Editor.unlink_override(editor, 'mix', layer, 'mix')
if 'mix' in layer['inputs']:
    failures.append("an override's own input was kept after it was given a value")
# The field of a connected input is greyed out, and stays so after it is dragged (tinted again).
from moonray_modo import parameter_state  # noqa: E402
from moonray_modo.node_widgets import NumericField  # noqa: E402
from PySide2 import QtGui  # noqa: E402
field = NumericField('mix', 'mix', -1, {'type': 'Float', 'default': '0.5'}, 0.0, kind='DwaMixMaterial', connected=True)
grey = QtGui.QColor(parameter_state.CONNECTED_COLOR)
if field.palette().color(QtGui.QPalette.Text) != grey:
    failures.append('a connected field is not greyed out')
field.setValue(0.7)
if field.palette().color(QtGui.QPalette.Text) != grey:
    failures.append('a connected field lost its grey after an edit')
free = NumericField('mix', 'mix', -1, {'type': 'Float', 'default': '0.5'}, 0.7, kind='DwaMixMaterial')
if free.palette().color(QtGui.QPalette.Text) == grey:
    failures.append('an unconnected field is greyed out')
print('\n'.join(failures) if failures else 'graph keeps links: all checks passed')
sys.exit(1 if failures else 0)
