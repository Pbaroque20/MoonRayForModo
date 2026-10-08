"""Exercise the MoonRay ramp editor without showing it. Needs a Python with PySide2, such as
Modo's bundled interpreter with QT_QPA_PLATFORM=offscreen."""
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'kit/MoonRayForModo/python'))
from PySide2 import QtWidgets
from moonray_modo import entities, ramp_editor

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

colours = ramp_editor.RampDialog('Colour ramp', [1.0, 0.0], [[0, 0, 1], [1, 0, 0]], [1, 4], True)
colours.add_stop()
positions, values, modes = colours.result()
assert positions == [0.0, 0.5, 1.0] and modes == [4, 1, 1], (positions, modes)
assert values[0] == [1, 0, 0] and values[2] == [0, 0, 1], values
# The new stop took the ramp's own colour half way along, by the first stop's blend.
assert abs(values[1][0] - (1 - 0.7071)) < 1e-3, values[1]
colours.table.selectRow(2)      # rows are in the order the stops were made; the new one is last
colours.remove_stop()
assert colours.result()[0] == [0.0, 1.0]
colours.grab()      # paints the preview

numbers = ramp_editor.RampDialog('Density ramp', [], [], [], False)
assert numbers.result() == ([0.0, 1.0], [1.0, 0.0], [1, 1]), numbers.result()
numbers.grab()

texts = [ramp_editor.text(v) for v in colours.result()]
assert texts == ['0 1', '1 0 0; 0 0 1', '4 1'], texts
kinds = ['FloatVector', 'RgbVector', 'IntVector']
assert [entities.parse_list(t, k) for t, k in zip(texts, kinds)] == [[0.0, 1.0], [[1.0, 0.0, 0.0], [0.0, 0.0, 1.0]], [4, 1]]
print('Ramp editor check passed')
