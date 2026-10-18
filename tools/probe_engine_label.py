# python
"""Isolated GUI test: the size and samples beside the preview's picture follow the engine chosen.

A ball, rendered 1280 x 720 at 4 x 4 pixel samples. Each engine is chosen in turn and what the label says is noted
before anything renders: MoonRay at the camera's size and its samples, MoonRay LS at its width limit and samples limit,
MoonLightIPR at the preview size and its samples. Then MoonLightIPR renders, and the label of its picture is noted. The
preview's preferences of the test Modo are put back as they were."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/engine-label'
out.mkdir(parents=True, exist_ok=True)
runtime = pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
KEYS = ('runtime', 'preview_size', 'ipr/width', 'ipr/samples', 'moonlightipr/samples')
result = {'labels': {}}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def prepare():
    panel = panel_widget()
    result['before'] = {key: panel.preferences.store.value(key) for key in KEYS}
    for key, value in (('runtime', str(runtime)), ('preview_size', 640), ('ipr/width', 320), ('ipr/samples', 64), ('moonlightipr/samples', 512)):
        panel.preferences.set(key, value)


def choose(engine):
    def go():
        panel = panel_widget()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(engine))
        QtWidgets.QApplication.processEvents()
        result['labels'][engine] = panel.image_info.text()
        save()
    return go


def render():
    panel_widget().start.click()


def rendered():
    panel = panel_widget()
    panel.stop()
    result['labels']['moonlightipr rendered'] = panel.image_info.text()
    save()


def put_back():
    panel = panel_widget()
    for key, value in result['before'].items():
        if value is None:
            panel.preferences.store.remove(key)
        else:
            panel.preferences.store.setValue(key, value)


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
    import modo
    modo.Scene().renderItem.channel('resX').set(1280)
    modo.Scene().renderItem.channel('resY').set(720)
    lx.eval('moonray.render.samples 4')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run([
    (prepare, 500), (choose('moonlightipr'), 1500), (choose('moonray_ls'), 1500), (choose('moonray'), 1500),
    (choose('moonlightipr'), 1500), (render, 10000), (rendered, 2000), (put_back, 500)]))
