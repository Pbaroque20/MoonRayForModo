# python
"""Isolated GUI test: the compositor's editor window.

Two balls are rendered with MoonRay. The editor is opened from the preview window as Options > Compositor does. A
Grade node is added with the beauty selected, wired on to the output, and its exposure set in its form; then a Glow
is added and wired between. Each time what the scene has stored, and whether the Composite buffer follows, is noted
and the editor saved as a picture. Last a wire that would make a loop is tried, a node is deleted, and Undo is used."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/compositor-editor'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def mean():
    image = panel_widget().preview.image
    if image.isNull():
        return None
    small = image.convertToFormat(QtGui.QImage.Format_RGB888).scaled(64, 36)
    data = bytes(small.constBits())[:64 * 36 * 3]
    return round(sum(data) / len(data), 1)


def note(name):
    panel = panel_widget(); editor = held.get('editor')
    from moonray_modo import compositor
    stored = panel._settings_values_stored().get('compositor') or {}
    frame = panel.renderer.buffers.frame or {}
    result['steps'].append({'step': name, 'stored_nodes': sorted(n['type'] for n in stored.get('nodes', {}).values()),
                            'stored_wires': sorted('%s.%s<-%s' % (n['type'], k, stored['nodes'][s]['type']) for n in stored.get('nodes', {}).values() for k, s in n['inputs'].items()),
                            'editor_nodes': len(editor.graph['nodes']) if editor else None, 'drawn': len(editor.items) if editor else None, 'wires_drawn': len(editor.links) if editor else None,
                            'form_rows': editor.form.rowCount() if editor else None, 'title': editor.property_title.text() if editor else None,
                            'composite_listed': panel.buffer.findData('composite') >= 0, 'composite_file': 'composite' in frame.get('files', {}),
                            'shown': panel.buffer.currentData(), 'brightness': mean(), 'info': editor.info.text()[:80] if editor else None})
    if editor:
        editor.grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(60000)
def render():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / 'runtime/steady-0351-tiles'))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel.start.click()


@step(2500)
def open_editor():
    panel = panel_widget()
    panel.buffer.setCurrentIndex(panel.buffer.findData('beauty'))
    panel.open_compositor()
    from moonray_modo import compositor_editor
    held['editor'] = compositor_editor._open.get('editor')
    result['opened'] = held['editor'] is not None
    result['status_after_open'] = panel.status.text()[:120]
    tree = held['editor'].node_tree
    result['library'] = {tree.topLevelItem(i).text(0): tree.topLevelItem(i).childCount() for i in range(tree.topLevelItemCount())}


@step(2500)
def add_grade():
    note('opened')
    editor = held['editor']
    editor.canvas.clearSelection(); editor.items['beauty'].setSelected(True)
    editor.add('grade')
    held['grade'] = editor.selected()



@step(3500)
def set_exposure():
    note('grade_added_and_wired')
    editor = held['editor']
    editor.canvas.clearSelection(); editor.items[held['grade']].setSelected(True)
    spin = next(f for f in editor.fields if isinstance(f, QtWidgets.QDoubleSpinBox))
    spin.setValue(2.0)
    editor.show_composite()


@step(5000)
def add_glow():
    note('exposure_two_stops_composite_shown')
    editor = held['editor']
    editor.canvas.clearSelection(); editor.items[held['grade']].setSelected(True)
    # From the library on the left, as a click on its row does.
    tree = editor.node_tree
    row = next(tree.topLevelItem(i).child(j) for i in range(tree.topLevelItemCount()) for j in range(tree.topLevelItem(i).childCount()) if tree.topLevelItem(i).child(j).text(0) == 'Glow')
    editor.add_from_library(row, 0)
    held['glow'] = editor.selected()

    result['loop_allowed'] = editor.can_connect(held['glow'], held['grade'], 'image')
    editor.frame(everything=True)


@step(5000)
def change_mode_and_delete():
    note('glow_added_after_the_grade')
    editor = held['editor']
    editor.canvas.clearSelection(); editor.items[held['glow']].setSelected(True)
    editor.remove()


@step(4000)
def undo():
    note('glow_deleted')
    held['editor'].undo()


@step(4000)
def clear():
    note('undone')
    held['editor'].clear()


@step(500)
def finish():
    note('cleared')
    held['editor'].close()
    panel_widget().stop()


def run(index=0):
    if index >= len(STEPS):
        save()
        lx.eval('!app.quit')
        return
    function, wait = STEPS[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append([function.__name__, traceback.format_exc()])
        save()
    QtCore.QTimer.singleShot(wait, lambda: run(index + 1))


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
save()
QtCore.QTimer.singleShot(8000, lambda: run())
