# python
"""Isolated GUI test: a light's material with its eye off in the Shader Tree, in Modo's renderer and in MoonRay.

A ball under Modo's directional light, whose light material is red, in an environment that gives no light. Modo's own
renderer and MoonRay each render it with the light material as it is, and with the light material's eye off. The mean
colour of each picture is written down, with what MoonRay was told of the light."""
import glob
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/light-material'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def mean(image):
    image = image.convertToFormat(QtGui.QImage.Format_RGB888).scaled(64, 36)
    data = bytes(image.constBits())[:image.bytesPerLine() * image.height()]
    row = image.bytesPerLine()
    sums = [0, 0, 0]
    for y in range(image.height()):
        for x in range(image.width()):
            for c in range(3):
                sums[c] += data[y * row + x * 3 + c]
    count = float(image.width() * image.height())
    return [round(v / count, 2) for v in sums]


def light():
    return next(item for item in modo.Scene().items('light') if item.type == 'sunLight')


def modo_render(name):
    """Modo's own renderer, to a PNG; its mean colour."""
    try:
        lx.eval('!render.animation {%s} PNG' % str(out / ('modo_' + name + '_')))
        files = sorted(glob.glob(str(out / ('modo_' + name + '_*'))))
        return {'file': files[-1], 'mean': mean(QtGui.QImage(files[-1]))} if files else {'error': 'no file written'}
    except Exception:
        return {'error': traceback.format_exc()}


def note(name):
    from moonray_modo import host
    panel = panel_widget()
    material = light().material
    told = [(v['name'], v['color'], v['intensity']) for v in host.snapshot().get('lights', [])]
    result['steps'].append({'step': name, 'light_material': material.name if material else None,
                            'light_material_enable': material.channel('enable').get() if material else None,
                            'moonray_mean': mean(panel.preview.image), 'moonray_told': told, 'modo': modo_render(name),
                            'rendering': panel._rendering, 'status': panel.status.text()[:80]})
    panel.window().grab().save(str(out / ('moonray_%s.png' % name)))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(30000)
def begin():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel.start.click()


@step(30000)
def eye_off():
    note('light_material_on')
    # As clicking the eye beside the light's material in the Shader Tree.
    lx.eval('!channel.value 0 channel:{%s:enable}' % light().material.id)
    panel_widget().start.click()


@step(500)
def finish_():
    note('light_material_eye_off')


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
    scene = modo.Scene()
    for environment in scene.items('environment'):
        environment.channel('radiance').set(0.0)
    for name, value in (('resX', 320), ('resY', 180), ('globEnable', False), ('first', 1), ('last', 1)):
        scene.renderItem.channel(name).set(value)
    material = light().material
    result['light_material_type'] = material.type if material else None
    for key, value in (('lightCol.R', 1.0), ('lightCol.G', 0.15), ('lightCol.B', 0.15)):
        lx.eval('!channel.value %s channel:{%s:%s}' % (value, material.id, key))
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run())
