# python
"""Isolated GUI test: the pixel samples of each realtime engine, set apart in the preview's preferences.

A ball. MoonLightIPR is set to 32 samples and MoonRay LS to 64. With realtime on in each, what is handed to the engine
is written down: MoonLightIPR is asked for 32, MoonRay LS for at most 64. The preferences dialog is pictured, and the
preferences are put back as they were."""
import json
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/ipr-samples'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {'asked': [], 'before': {}}
KEYS = ('moonlightipr/samples', 'ipr/samples')


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(8000)
def moonlightipr():
    from moonray_modo.preferences import Dialog
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / 'runtime/steady-0351-tiles'))
    held['before'] = {key: panel.preferences.get(key) for key in KEYS}
    dialog = Dialog(panel.preferences, panel)
    dialog.show()
    QtWidgets.QApplication.processEvents()
    result['choices'] = {key: [dialog.widgets[key].itemData(i) for i in range(dialog.widgets[key].count())] for key in KEYS}
    result['rows'] = [dialog.layout().itemAt(i).widget().text() for i in range(dialog.layout().count())
                      if isinstance(dialog.layout().itemAt(i).widget(), (QtWidgets.QLabel, QtWidgets.QCheckBox))]
    # As choosing in the dialog and pressing OK does.
    dialog.widgets['moonlightipr/samples'].setCurrentIndex(dialog.widgets['moonlightipr/samples'].findData(32))
    dialog.widgets['ipr/samples'].setCurrentIndex(dialog.widgets['ipr/samples'].findData(64))
    QtWidgets.QApplication.processEvents()
    dialog.grab().save(str(out / 'preferences.png'))
    dialog.accept()
    session, submit = panel.renderer.moonlightipr, panel.renderer.submit
    sent = session.submit

    def ipr(snapshot, directory, width, height, environment, generation, samples=256, *a, **k):
        held['asked'].append(['MoonLightIPR', samples])
        return sent(snapshot, directory, width, height, environment, generation, samples, *a, **k)

    def any_engine(scene, *a, **k):
        if k.get('engine') == 'moonray':
            held['asked'].append(['MoonRay LS', scene.get('render_settings', {}).get('max_adaptive_samples'), scene.get('_ipr')])
        return submit(scene, *a, **k)
    session.submit, panel.renderer.submit = ipr, any_engine
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
    QtWidgets.QApplication.processEvents()
    panel.start.click()


@step(20000)
def moonray_ls():
    panel = panel_widget()
    result['moonlightipr'] = list(held['asked'])
    held['asked'] = []
    panel.stop()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray_ls'))
    QtWidgets.QApplication.processEvents()
    panel.start.click()


@step(1000)
def finish_():
    panel = panel_widget()
    result['moonray_ls'] = list(held['asked'])
    panel.stop()
    for key, value in held['before'].items():
        panel.preferences.set(key, value)
    result['put_back'] = {key: panel.preferences.get(key) for key in KEYS}


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
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
