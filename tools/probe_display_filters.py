# python
"""Isolated GUI test: MoonRay display filters as Modo items, shown as buffers of the preview and written to the EXR.

Two balls, red and green. A ColorCorrectDisplayFilter item, Grey, takes the colour out of the beauty and brightens it
one stop; a second one, Blue, takes Grey in and multiplies it by blue. The preview renders with MoonRay; the beauty,
Grey and Blue buffers are each chosen and their colours written down. Then the scene MoonRay was given is written
out as it would be for a final render, for tools/check_display_filters.py's --final to render and read."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/display-filters-gui'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def colours():
    """The average colour of the picture's bright pixels in its left and right halves."""
    image = panel_widget().preview.image.convertToFormat(QtGui.QImage.Format_RGB888)
    found = []
    for x0, x1 in ((0, image.width() // 2), (image.width() // 2, image.width())):
        total, count = [0, 0, 0], 0
        for y in range(0, image.height(), 2):
            for x in range(x0, x1, 2):
                c = image.pixelColor(x, y)
                if max(c.red(), c.green(), c.blue()) > 40:
                    total = [total[0] + c.red(), total[1] + c.green(), total[2] + c.blue()]
                    count += 1
        found.append([round(v / count, 1) for v in total] + [count] if count else None)
    return found


def note(name):
    panel = panel_widget()
    result['steps'].append({'step': name, 'buffer': panel.buffer.currentData(), 'buffer_label': panel.buffer.currentText(),
                            'left_red_right_green': colours(), 'status': panel.status.text()[:90]})
    panel.preview.grab().save(str(out / ('%s.png' % name)))
    save()


def choose(label):
    panel = panel_widget()
    index = panel.buffer.findText(label)
    result.setdefault('menu', [panel.buffer.itemText(i) for i in range(panel.buffer.count())])
    if index < 0:
        raise RuntimeError('No %s buffer in %s' % (label, result['menu']))
    panel.buffer.setCurrentIndex(index)


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(40000)
def render():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-042-display')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel.start.click()


@step(4000)
def grey():
    note('beauty')
    choose('Grey')


@step(4000)
def blue():
    note('grey')
    choose('Blue')


@step(500)
def finish_():
    note('blue')
    panel = panel_widget()
    panel.stop()
    try:
        from moonray_modo import rdla
        snapshot = (panel.renderer.active or {}).get('snapshot') or {}
        final = dict(snapshot)
        final.pop('preview_buffer_files', None)
        (out / 'final.rdla').write_text(rdla.scene_text(final, 320, 180, 4, 0.0, str(out / 'final.exr')), encoding='utf-8')
        result['final_rdla'] = str(out / 'final.rdla')
    except Exception:
        result['final_error'] = traceback.format_exc()


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
    scene = modo.Scene()
    for x, tag, colour in ((-0.6, 'Red', '{1.0 0.0 0.0}'), (0.6, 'Green', '{0.0 1.0 0.0}')):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
        lx.eval('poly.setMaterial %s %s 0.8 0.04 true false' % (tag, colour))
    from moonray_modo import entities
    made = {}
    for name in ('Grey', 'Blue'):
        before = {item.id for item in scene.items(entities.item_type('ColorCorrectDisplayFilter'), superType=False)}
        lx.eval('moonray.entity.add ColorCorrectDisplayFilter')
        item = next(item for item in scene.items(entities.item_type('ColorCorrectDisplayFilter'), superType=False) if item.id not in before)
        item.name = name
        made[name] = item
    grey_item, blue_item = made['Grey'], made['Blue']
    result['started_input'] = grey_item.channel(entities.CHANNEL_PREFIX + 'input').get()
    grey_item.channel(entities.CHANNEL_PREFIX + 'saturation').set(0.0)
    grey_item.channel(entities.CHANNEL_PREFIX + 'exposure').set(1.0)
    blue_item.channel(entities.CHANNEL_PREFIX + 'input').set('Grey')
    for part, value in (('R', 0.0), ('G', 0.0), ('B', 1.0)):
        blue_item.channel(entities.CHANNEL_PREFIX + 'multiply.' + part).set(value)
    lx.eval('moonray.render.samples 4')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
if 'error' in result:
    QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
else:
    QtCore.QTimer.singleShot(15000, lambda: run())
