# python
"""Isolated GUI test: an image layer's Low Value and High Value are followed.

A ball wearing a white image as its diffuse colour, under Modo's directional light, in a black environment. It is
rendered with the engine in MOONRAY_PROBE_ENGINE as it is; with High Value at 20%, which should leave it a fifth as
bright; and with Low Value at 100% and High Value at 0% over a black image's stand-in (the white image turned black),
which should leave it black. How bright the picture is each time is written down."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
ENGINE = os.environ.get('MOONRAY_PROBE_ENGINE', 'moonlightipr')
out = root / 'test-results/low-high'
out.mkdir(parents=True, exist_ok=True)
result = {'engine': ENGINE, 'steps': []}
held = {}


def save():
    (out / (ENGINE + '.json')).write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def bright():
    image = panel_widget().preview.image.convertToFormat(QtGui.QImage.Format_RGB888).scaled(64, 36)
    data = bytes(image.constBits())[:image.bytesPerLine() * image.height()]
    return round(sum(data) / float(len(data)), 2) if data else None


def note(name):
    panel = panel_widget()
    layer = held['layer']
    result['steps'].append({'step': name, 'brightness': bright(), 'low': layer.channel('min').get(), 'high': layer.channel('max').get(),
                            'status': panel.status.text()[:80]})
    panel.window().grab().save(str(out / ('%s_%d_%s.png' % (ENGINE, len(result['steps']), name))))
    save()


def put(name, value):
    lx.eval('channel.value %s channel:{%s:%s}' % (value, held['layer'].id, name))


def render():
    if ENGINE == 'moonray':
        panel_widget().start.click()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


WAIT = 25000 if ENGINE == 'moonray' else 8000


@step(WAIT)
def begin():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(ENGINE))
    from moonray_modo import host
    scene = host.snapshot(refresh_materials=True)
    result['warnings'] = scene['warnings'][:8]
    result['tree'] = [[item.name, item.type, item.parent.name if item.parent else None] for item in modo.Scene().items('textureLayer')]
    result['layers'] = {key: [[layer.get('kind'), layer.get('effect'), layer.get('corrections')] for layer in (material.get('layers') or [])] if isinstance(material, dict) else None
                        for key, material in scene['materials'].items()}
    result['meshes'] = [[mesh.get('name'), mesh.get('material'), len(mesh.get('uvs') or [])] for mesh in scene['meshes']]
    panel.start.click()


@step(WAIT)
def high_fifth():
    note('as_it_is')
    put('max', 0.2)
    render()


@step(WAIT)
def turned_over():
    note('high_value_20')
    put('min', 1.0)
    put('max', 0.0)
    render()


@step(500)
def finish_():
    # White comes out as High Value: 0.
    note('low_100_high_0')
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
    picture = QtGui.QImage(64, 64, QtGui.QImage.Format_RGB888)
    picture.fill(QtGui.QColor(255, 255, 255))
    path = out / 'white.png'
    picture.save(str(path))
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    lx.eval('poly.setMaterial Ball {0.8 0.8 0.8} 0.8 0.04 true false')
    for environment in modo.Scene().items('environment'):
        environment.channel('radiance').set(0.0)
    lx.eval('clip.addStill {%s}' % str(path).replace('\\', '/'))
    lx.eval('select.item {%s} set' % next(item for item in modo.Scene().items('mask') if 'Ball' in item.name).id)
    lx.eval('texture.new clip:{white:videoStill001}')
    held['layer'] = next(iter(modo.Scene().items('imageMap')))
    # Under the Render item, above the base material: it colours everything.
    lx.eval('texture.parent {%s} 2 item:{%s}' % (modo.Scene().renderItem.id, held['layer'].id))
    result['layer'] = [held['layer'].name, held['layer'].channel('effect').get(), held['layer'].parent.name if held['layer'].parent else None]
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
if 'error' in result:
    QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
else:
    QtCore.QTimer.singleShot(8000, lambda: run())
