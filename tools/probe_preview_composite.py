# python
"""Isolated GUI test: the compositor's Preview Composite and Send Composite to Preview Window.

A ball is rendered with MoonRay. In the compositor, a Grade (an orange tint) is put between the beauty and the
Composite. Preview Composite is switched on: the viewer under the settings is noted and the window pictured. The Grade
is changed: the viewer is noted again, having followed the new Composite. Send Composite to Preview Window is pressed:
the preview window's buffer is noted."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/preview-composite'
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


def build():
    from moonray_modo import compositor_editor
    panel = panel_widget()
    panel.open_compositor()
    editor = compositor_editor._open.get('editor')
    held['editor'] = editor
    before = set(editor.graph['nodes'])
    editor.add('grade', QtCore.QPointF(130, 0), (editor.graph['root'], 'image'), {'tint': [1.0, 0.5, 0.1]})
    held['grade'] = next(n for n in editor.graph['nodes'] if n not in before)
    editor.graph['nodes'][held['grade']]['inputs'] = {'image': 'beauty'}
    editor.rebuild(); editor.write()


def preview():
    editor = held['editor']
    editor.preview_button.setChecked(True)
    QtWidgets.QApplication.processEvents()


def look(label):
    def go():
        editor = held['editor']
        image = editor.mini_view.image
        middle = image.pixelColor(image.width() // 2, image.height() // 2).name() if not image.isNull() else None
        result[label] = {'shown': editor.mini.isVisible(), 'size': [image.width(), image.height()], 'note': editor.mini_note.text(), 'middle': middle}
        editor.grab().save(str(out / (label + '.png')))
    return go


def change():
    editor = held['editor']
    editor.set_value(held['grade'], 'tint', [0.1, 0.5, 1.0])
    editor.write()


def send():
    held['editor'].show_composite()


def sent():
    panel = panel_widget()
    result['preview_window_buffer'] = panel.buffer.currentData()
    held['editor'].close()
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
QtCore.QTimer.singleShot(8000, lambda: run([(render, 40000), (build, 8000), (preview, 3000), (look('first'), 100),
                                            (change, 8000), (look('after_change'), 100), (send, 3000), (sent, 300)]))
