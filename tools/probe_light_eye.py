# python
"""Isolated GUI test: a directional light with its eye off lights nothing, and lights again with its eye on.

A ball under Modo's own directional light, in an environment that gives no light of its own (black), so that what
lights the ball is the light alone. With the engine in MOONRAY_PROBE_ENGINE (moonray, or moonlightipr with realtime
on) the picture is made with the light as it is, with its eye off, and with its eye on again; how bright the picture
is each time is written down, and the window pictured."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
ENGINE = os.environ.get('MOONRAY_PROBE_ENGINE', 'moonlightipr')
# MOONRAY_PROBE_ENVIRONMENT=1 leaves Modo's own environment as it is.
PLAIN = os.environ.get('MOONRAY_PROBE_ENVIRONMENT') != '1'
tag = ENGINE + ('' if PLAIN else '-environment') + ('-follow' if os.environ.get('MOONRAY_PROBE_FOLLOW') == '1' else '')
out = root / 'test-results/light-eye'
out.mkdir(parents=True, exist_ok=True)
result = {'engine': ENGINE, 'steps': []}
held = {}


def save():
    (out / (tag + '.json')).write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def bright():
    image = panel_widget().preview.image.convertToFormat(QtGui.QImage.Format_RGB888).scaled(64, 36)
    data = bytes(image.constBits())[:image.bytesPerLine() * image.height()]
    return round(sum(data) / float(len(data)), 2) if data else None


def note(name):
    panel = panel_widget()
    lights = [(light.name, light.type, light.channel('visible').get(), light.channel('render').get()) for light in modo.Scene().items('light')]
    result['steps'].append({'step': name, 'brightness': bright(), 'lights': lights, 'following': panel._following, 'rendering': panel._rendering,
                            'status': panel.status.text()[:80],
                            'notices': [w for w in ((panel.renderer.active or {}).get('snapshot', {}).get('warnings') or []) if 'lit by the environment' in w]})
    panel.window().grab().save(str(out / ('%s_%d_%s.png' % (tag, len(result['steps']), name))))
    save()


def light():
    return next(item for item in modo.Scene().items('light') if item.type == 'sunLight')


def render():
    panel = panel_widget()
    if ENGINE == 'moonray':
        panel.start.click()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


WAIT = 25000 if ENGINE == 'moonray' else 7000


@step(WAIT)
def begin():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(ENGINE))
    # MOONRAY_PROBE_FOLLOW=1: the environment lights the scene as Modo has it, only with Global Illumination on.
    held['was'] = panel.preferences.get('environment_lighting')
    panel.preferences.set('environment_lighting', 'modo' if os.environ.get('MOONRAY_PROBE_FOLLOW') == '1' else 'moonray')
    result['global_illumination'] = modo.Scene().renderItem.channel('globEnable').get()
    panel.start.click()


@step(WAIT)
def eye_off():
    note('light_on')
    # As clicking the eye beside the light in the item list.
    lx.eval('select.item {%s} set' % light().id)
    lx.eval('item.channel locator$visible off')
    render()


@step(WAIT)
def eye_on():
    note('light_eye_off')
    lx.eval('select.item {%s} set' % light().id)
    lx.eval('item.channel locator$visible default')
    render()


@step(500)
def finish_():
    note('light_eye_on_again')
    panel_widget().stop()
    panel_widget().preferences.set('environment_lighting', held.get('was', 'moonray'))


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
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    if PLAIN:
        for environment in modo.Scene().items('environment'):
            environment.channel('radiance').set(0.0)
    result['environments'] = [(e.name, e.channel('radiance').get(), e.channel('visCam').get()) for e in modo.Scene().items('environment')]
    if os.environ.get('MOONRAY_PROBE_FOLLOW') == '1':
        # Global Illumination off in the Render item, as a scene lit by its lights alone has it.
        lx.eval('channel.value 0 channel:{%s:globEnable}' % modo.Scene().renderItem.id)
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
