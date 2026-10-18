# python
"""Isolated GUI test: the compositor's probe mode as a tooltip at the pointer, and probe notes that follow the graph.

A ball is rendered with MoonRay. In the compositor, probe mode is switched on and the preview is told the pointer is
over a pixel of the ball: the tooltip's words are noted. A probe note is made at that pixel, as the preview's right-click
makes it, and its words noted. Then a Grade raising the exposure is put between the beauty and the Composite: the note's
words are noted again once it has followed. The canvas and the preview's right-click menu are pictured."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/compositor-probe-note'
out.mkdir(parents=True, exist_ok=True)
runtime = pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def render():
    panel = panel_widget()
    held['runtime'] = panel.preferences.store.value('runtime')
    panel.preferences.set('runtime', str(runtime))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel.start.click()


def probe():
    from moonray_modo import compositor_editor
    panel = panel_widget()
    result['rendering_still'] = panel._rendering
    panel.open_compositor()
    editor = compositor_editor._open.get('editor')
    held['editor'] = editor
    editor.probe_button.setChecked(True)
    image = panel.preview.image
    held['pixel'] = (image.width() // 2, image.height() // 2)
    editor.probe_hovered(*held['pixel'])
    editor.update_probe()
    QtWidgets.QApplication.processEvents()
    result['tooltip'] = QtWidgets.QToolTip.text()
    result['tooltip_shown'] = QtWidgets.QToolTip.isVisible()
    menu = panel._image_menu(QtCore.QPoint(10, 10))
    result['preview_menu'] = [action.text() for action in menu.actions() if action.text()][:4]


def note():
    editor = held['editor']
    editor.note_at(held['pixel'])
    notes = [node for node in editor.graph['nodes'].values() if node['type'] == 'note']
    result['note_parameters'] = notes[-1]['parameters'] if notes else None
    # A Grade raising the exposure, between the beauty and the Composite.
    before = set(editor.graph['nodes'])
    editor.add('grade', QtCore.QPointF(130, 0), (editor.graph['root'], 'image'), {'exposure': 1.0})
    grade = next(n for n in editor.graph['nodes'] if n not in before)
    editor.graph['nodes'][grade]['inputs'] = {'image': 'beauty'}
    editor.graph['nodes'][editor.graph['root']]['inputs'] = {'image': grade}
    editor.rebuild(); editor.changed()


def followed():
    editor = held['editor']
    notes = [node for node in editor.graph['nodes'].values() if node['type'] == 'note']
    result['note_after_grade'] = notes[-1]['parameters']['text'] if notes else None
    editor.frame(everything=True)
    QtWidgets.QApplication.processEvents()
    editor.grab().save(str(out / 'editor.png'))
    editor.probe_button.setChecked(False)
    editor.close()
    panel = panel_widget()
    if held.get('runtime') is None:
        panel.preferences.store.remove('runtime')
    else:
        panel.preferences.store.setValue('runtime', held['runtime'])


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
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run([(render, 40000), (probe, 1500), (note, 3000), (followed, 500)]))
