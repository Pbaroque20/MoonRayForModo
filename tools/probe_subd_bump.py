# python
"""Isolated GUI test: a bump image shows on a subdivision surface as it does on plain polygons.

A ball wearing a chequered image as its bump, under Modo's directional light in a black environment. It is rendered
with the engine in MOONRAY_PROBE_ENGINE as plain polygons, and again with its polygons made a subdivision surface
(Catmull-Clark, as Tab-Shift makes them). The picture of each is saved, and how much the ball's shading varies from
pixel to pixel (which the bumps are what makes) is written down."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
ENGINE = os.environ.get('MOONRAY_PROBE_ENGINE', 'moonray')
out = root / 'test-results/subd-bump'
out.mkdir(parents=True, exist_ok=True)
result = {'engine': ENGINE, 'steps': []}
held = {}


def save():
    (out / (ENGINE + '.json')).write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def rough():
    """How much neighbouring pixels of the picture differ, on average: the bumps are what makes them."""
    image = panel_widget().preview.image.convertToFormat(QtGui.QImage.Format_Grayscale8).scaled(320, 180)
    width, height, line = image.width(), image.height(), image.bytesPerLine()
    data = bytes(image.constBits())[:line * height]
    total = count = 0
    for y in range(height):
        row = data[y * line:y * line + width]
        for x in range(1, width):
            if row[x] > 8 and row[x - 1] > 8:
                total += abs(row[x] - row[x - 1])
                count += 1
    return round(total / float(count), 3) if count else None


def note(name):
    panel = panel_widget()
    mesh = held['mesh']
    kinds = sorted({polygon.accessor.Type() for polygon in mesh.geometry.polygons})
    result['steps'].append({'step': name, 'shading_varies_by': rough(), 'polygon_types': kinds, 'status': panel.status.text()[:80],
                            'log': sorted({line.strip()[:200] for line in str(getattr(panel.renderer, 'log', '') or '').splitlines() if 'unavailable' in line or 'WARN' in line})[:8]})
    panel.preview.image.save(str(out / ('%s_%d_%s.png' % (ENGINE, len(result['steps']), name))))
    save()


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


WAIT = 30000 if ENGINE == 'moonray' else 9000


@step(WAIT)
def begin():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(ENGINE))
    from moonray_modo import host, rdla
    text = rdla.scene_text(host.snapshot(refresh_materials=True), 640, 360, 2, 0.0)
    (out / 'scene.rdla.txt').write_text(chr(10).join(line[:400] for line in text.splitlines()), encoding='utf-8')
    panel.start.click()


@step(WAIT)
def subdivide():
    note('plain_polygons')
    lx.eval('select.item {%s} set' % held['mesh'].id)
    lx.eval('select.typeFrom polygon')
    lx.eval('select.all')
    lx.eval('poly.convert face psubdiv true')
    lx.eval('select.typeFrom item')
    if ENGINE == 'moonray':
        panel_widget().start.click()


@step(500)
def finish_():
    note('subdivision_surface')
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
    picture = QtGui.QImage(256, 256, QtGui.QImage.Format_RGB888)
    picture.fill(QtGui.QColor(0, 0, 0))
    painter = QtGui.QPainter(picture)
    for y in range(16):
        for x in range(16):
            if (x + y) % 2:
                painter.fillRect(x * 16, y * 16, 16, 16, QtGui.QColor(255, 255, 255))
    painter.end()
    path = out / 'cheques.png'
    picture.save(str(path))
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    held['mesh'] = modo.Scene().selected[0]
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    for environment in modo.Scene().items('environment'):
        environment.channel('radiance').set(0.0)
    lx.eval('clip.addStill {%s}' % str(path).replace('\\', '/'))
    lx.eval('texture.new clip:{cheques:videoStill001}')
    layer = next(iter(modo.Scene().items('imageMap')))
    # In a material of the ball's own, as an artist has it.
    lx.eval('select.item {%s} set' % held['mesh'].id)
    lx.eval('select.typeFrom polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial Ball {0.8 0.8 0.8} 0.8 0.04 true false')
    lx.eval('select.typeFrom item')
    mask = next(item for item in modo.Scene().items('mask') if 'Ball' in item.name)
    lx.eval('texture.parent {%s} 2 item:{%s}' % (mask.id, layer.id))
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('shader.setEffect bump')
    result['layer'] = [layer.name, layer.channel('effect').get()]
    for material in modo.Scene().items('advancedMaterial'):
        lx.eval('channel.value 0.02 channel:{%s:bumpAmp}' % material.id)
    lx.eval('moonray.render.samples 3')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
if 'error' in result:
    QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
else:
    QtCore.QTimer.singleShot(8000, lambda: run())
