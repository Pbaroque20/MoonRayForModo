# python
"""Isolated GUI test: a red material colour (FF0000) against a red image (FF0000) on the same material.

The left ball's material is pure red; the right ball's is white with a pure red PNG as its colour layer. Both are
rendered with MoonRay and with MoonLightIPR, in the scene's linear Rec.709 working space and again in ACEScg. For each,
the red balls' average colour on screen is written down, with what MoonRay was told of each material and the image."""
import json
import os
import pathlib
import re
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / ('test-results/red-texture' + os.environ.get('MOONRAY_PROBE_TAG', ''))
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def halves():
    """The average colour of the red pixels in the left and the right half of the picture."""
    image = panel_widget().preview.image.convertToFormat(QtGui.QImage.Format_RGB888)
    found = []
    for x0, x1 in ((0, image.width() // 2), (image.width() // 2, image.width())):
        total, count = [0, 0, 0], 0
        for y in range(0, image.height(), 2):
            for x in range(x0, x1, 2):
                c = image.pixelColor(x, y)
                if c.red() > 30 and c.red() > 2 * c.green() and c.red() > 2 * c.blue():
                    total = [total[0] + c.red(), total[1] + c.green(), total[2] + c.blue()]
                    count += 1
        found.append([round(v / count, 1) for v in total] + [count] if count else None)
    return found


def told():
    """How MoonRay's scene text gives the two materials' colours."""
    try:
        from moonray_modo import host, rdla
        panel = panel_widget()
        text = (panel.renderer.active or {}).get('text') or ''
        if not text:
            return None
        lines = [l.strip() for l in text.splitlines() if re.search(r'albedo|base_color|\["color"\]|"texture"|mode"\] = 10|foreground|ImageMap\(|ModoTextureMap\(', l)]
        return lines[:40]
    except Exception as exc:
        return str(exc)


def note(name):
    panel = panel_widget()
    snapshot = (panel.renderer.active or {}).get('snapshot') or {}
    materials = {tag: {k: v for k, v in (m or {}).items() if k in ('color', 'diffCol', 'name')} for tag, m in (snapshot.get('materials') or {}).items()}
    tex = (snapshot.get('materials') or {}).get('Tex') or {}
    result.setdefault('layers', [{k: v for k, v in layer.items() if k not in ('uv_set',)} for layer in (tex.get('layers') or [])])
    try:
        # MoonRay's scene text for what was rendered, as the plugin writes it.
        if snapshot and not (out / ('%s.rdla' % name)).exists():
            from moonray_modo import rdla
            (out / ('%s.rdla' % name)).write_text(rdla.scene_text(snapshot, 320, 180, 2, 0.0, str(out / 'unused.exr')), encoding='utf-8')
    except Exception:
        result['text_error'] = traceback.format_exc()
    result['steps'].append({'step': name, 'engine': panel.preview_engine.currentData(), 'left_material_right_image': halves(),
                            'working_space': (snapshot.get('asset_settings') or {}).get('working_space'), 'materials': materials,
                            'status': panel.status.text()[:70]})
    panel.preview.grab().save(str(out / ('%s.png' % name)))
    save()


def working(space):
    panel = panel_widget()
    held_settings = dict(panel._settings_values().get('asset_settings') or {})
    held_settings['working_space'] = space
    panel._store(asset_settings=held_settings)


STEPS = []


def step(wait):
    def register(function):
        STEPS.append((function, wait))
        return function
    return register


@step(25000)
def moonray_rec709():
    panel = panel_widget()
    panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel.start.click()


@step(8000)
def ipr_rec709():
    note('moonray_rec709')
    panel = panel_widget()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
    panel.start.click()


@step(25000)
def moonray_acescg():
    note('moonlightipr_rec709')
    panel = panel_widget()
    panel.stop()
    working('acescg')
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel.start.click()


@step(8000)
def ipr_acescg():
    note('moonray_acescg')
    panel = panel_widget()
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
    panel.start.click()


@step(500)
def finish_():
    note('moonlightipr_acescg')
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
    picture.fill(QtGui.QColor(255, 0, 0))
    path = out / 'red.png'
    picture.save(str(path))
    scene = modo.Scene()
    for x, tag, colour in ((-0.6, 'Flat', '{1.0 0.0 0.0}'), (0.6, 'Tex', '{1.0 0.0 0.0}' if os.environ.get('MOONRAY_PROBE_LAYER') == 'none' else '{1.0 1.0 1.0}')):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        lx.eval('tool.attr prim.sphere cenX %s' % x)
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
        lx.eval('poly.setMaterial %s %s %s 0.04 true false' % (tag, colour, os.environ.get('MOONRAY_PROBE_DIFFUSE', '0.8')))
    mask = next(item for item in scene.items('mask') if 'Tex' in item.name)
    if os.environ.get('MOONRAY_PROBE_LAYER') == 'none':
        # The control: both balls plain red, no layer at all.
        result['image'] = 'none'
    elif os.environ.get('MOONRAY_PROBE_LAYER') == 'constant':
        # A constant red layer in place of the image: a layer through the same texture graph, with no file.
        lx.eval('select.item {%s} set' % mask.id)
        lx.eval('shader.create constant')
        layer = next(iter(scene.items('constant')))
        lx.eval('texture.parent {%s} %d item:{%s}' % (mask.id, len(mask.children()), layer.id))
        for part, value in (('R', 1.0), ('G', 0.0), ('B', 0.0)):
            lx.eval('channel.value %s channel:{%s:color.%s}' % (value, layer.id, part))
        result['image'] = {'layer': layer.name, 'effect': layer.channel('effect').get(), 'parent': layer.parent.name if layer.parent else None,
                           'color': [layer.channel('color.' + c).get() for c in 'RGB']}
    else:
        lx.eval('clip.addStill {%s}' % str(path).replace('\\', '/'))
        clip = next(iter(scene.items('videoStill')))
        lx.eval('select.item {%s} set' % mask.id)
        lx.eval('texture.new clip:{%s}' % clip.id)
        layer = next(iter(scene.items('imageMap')))
        # Inside the red-image ball's material group, at the top: it colours that material only.
        lx.eval('texture.parent {%s} %d item:{%s}' % (mask.id, len(mask.children()), layer.id))
        result['image'] = {'clip': clip.name, 'colorspace': clip.channel('colorspace').get() if 'colorspace' in [c.name for c in clip.channels()] else None,
                           'layer_effect': layer.channel('effect').get(), 'parent': layer.parent.name if layer.parent else None}
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
if 'error' in result:
    QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))
else:
    QtCore.QTimer.singleShot(15000, lambda: run())
