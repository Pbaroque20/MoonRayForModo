# python
"""Isolated GUI test: the preview lets go of its render when the scene it was rendered from is closed.

A ball is rendered with MoonLightIPR. A second scene is made and closed again: the picture, of the scene still open,
is kept. Then the scene rendered is closed, the last one open, so that Modo makes a blank one in its place: the picture
is cleared. Modo's notices of scenes made and closed are counted throughout, those of an idle Modo among them, and
what tells each scene apart (its name, file and render item) is noted at each step."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/scene-close'
out.mkdir(parents=True, exist_ok=True)
runtime = pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
result = {'steps': [], 'notices': {'made': 0, 'closed': 0}}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def count():
    from moonray_modo.changes import Changes
    made, closed = Changes.sil_SceneCreate, Changes.sil_SceneDestroy

    def on_made(self, *args):
        result['notices']['made'] += 1
        made(self, *args)

    def on_closed(self, *args):
        result['notices']['closed'] += 1
        closed(self, *args)
    Changes.sil_SceneCreate, Changes.sil_SceneDestroy = on_made, on_closed


def note(label):
    def go():
        panel = panel_widget()
        result['steps'].append({'step': label, 'scene': panel._scene_key(), 'rendered_scene': panel._rendered_scene,
                                'picture': not panel.preview.image.isNull(), 'status': panel.status.text(),
                                'rendering': panel._rendering, 'notices': dict(result['notices'])})
        save()
    return go


def render():
    panel = panel_widget()
    panel.preferences.set('runtime', str(runtime))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
    panel.start.click()


def stop():
    panel_widget().stop()


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
    count()
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run([
    (note('opened'), 5000), (note('idle five seconds'), 100),
    (render, 10000), (stop, 3000), (note('rendered'), 100),
    (lambda: lx.eval('scene.new'), 3000), (note('second scene made'), 100),
    (lambda: lx.eval('!scene.close'), 3000), (note('second scene closed'), 100),
    (lambda: lx.eval('!scene.close'), 3000), (note('rendered scene closed'), 100)]))
