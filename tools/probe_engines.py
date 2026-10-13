# python
"""Isolated GUI test: the three preview engines, and the button that goes with each.

MoonRay renders once, and its button reads Render and Stop. So does MoonRay LS, smaller and at few samples, and it
does not follow the scene. MoonLightIPR is realtime: it is chosen with realtime off, its button reads RT Off, and
pressing it switches realtime on (RT On) and off again. After each step the
button, whether the window is following the scene, and the window itself are written down."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/engines'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def note(name):
    panel = panel_widget()
    result['steps'].append({'step': name, 'engine': panel.preview_engine.currentText(), 'button': panel.start.text(), 'pressed': panel.start.isChecked(), 'following': panel._following,
                            'rendering': panel._rendering, 'status': panel.status.text(), 'timing': panel.render_timing.text(), 'info': panel.image_info.text(),
                            'picture': not panel.preview.image.isNull(), 'live_box_shown': panel.ipr_mode.isVisible(),
                            'engines': [panel.preview_engine.itemText(i) for i in range(panel.preview_engine.count())]})
    panel.window().grab().save(str(out / ('%02d_%s.png' % (len(result['steps']), name))))
    save()


def choose(engine):
    panel = panel_widget()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(engine))


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()

STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(3000)
def start():
    panel = panel_widget()
    held['stored'] = [panel.preferences.store.value(key, None) for key in ('runtime', 'preview_engine', 'ipr')]
    panel.preferences.set('runtime', str(root / 'runtime/steady-04-drain'))
    choose('moonray')


@step(25000)
def moonray_render():
    note('moonray_chosen')
    panel_widget().start.click()


@step(12000)
def low_sample():
    note('moonray_rendered')
    choose('moonray_ls')


@step(3000)
def low_sample_off():
    note('moonray_ls_chosen')
    panel_widget().start.click()


@step(1500)
def low_sample_rendering():
    note('moonray_ls_render_pressed')


@step(20000)
def low_sample_edit():
    # An edit after the render: MoonRay LS does not follow it.
    held['renders'] = panel_widget().renderer.generation
    lx.eval('select.item {%s} set' % modo.Scene().items('mesh')[0].id)
    lx.eval('transform.channel pos.Y 0.3')


@step(6000)
def moonlightipr():
    result['renders_for_an_edit_with_ls'] = panel_widget().renderer.generation - held['renders']
    result['ls_picture'] = [panel_widget().preview.image.width(), panel_widget().preview.image.height()]
    note('moonray_ls_rendered_then_edited')
    choose('moonlightipr')


@step(3000)
def moonlightipr_off():
    note('moonlightipr_chosen_rt_off')
    panel_widget().start.click()


@step(8000)
def moonlightipr_on():
    note('moonlightipr_rt_on')
    panel_widget().start.click()


@step(4000)
def back_to_moonray():
    note('moonlightipr_rt_off_again')
    choose('moonray')


@step(500)
def finish():
    note('moonray_again')
    panel = panel_widget()
    if panel._rendering or panel._following:
        panel.stop()
    for key, value in zip(('runtime', 'preview_engine', 'ipr'), held['stored']):
        if value is None:
            panel.preferences.store.remove(key)
        else:
            panel.preferences.store.setValue(key, value)
    result['restored'] = [panel.preferences.store.value(key, None) for key in ('runtime', 'preview_engine', 'ipr')]


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


QtCore.QTimer.singleShot(8000, run)
