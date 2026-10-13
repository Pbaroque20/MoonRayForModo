# python
"""Isolated GUI test: Modo's Cellular, Wood, Weave and Ripples layers show in a render.

A ball under Modo's light in a black environment, wearing one of those layers as its diffuse colour
(MOONRAY_PROBE_KIND), rendered with the engine in MOONRAY_PROBE_ENGINE. What reading the scene says of the layer, the
status and the picture are kept."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
ENGINE = os.environ.get('MOONRAY_PROBE_ENGINE', 'moonray')
KIND = os.environ.get('MOONRAY_PROBE_KIND', 'cellular')
tag = '%s-%s' % (ENGINE, KIND)
out = root / 'test-results/procedural-layers'
out.mkdir(parents=True, exist_ok=True)
result = {'engine': ENGINE, 'kind': KIND}


def save():
    (out / (tag + '.json')).write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin():
    try:
        from moonray_modo import host
        scene = host.snapshot(refresh_materials=True)
        result['warnings'] = scene['warnings']
        result['layers'] = {key: [[layer.get('kind'), layer.get('effect'), sorted((layer.get('procedural') or {}))[:6]] for layer in (material.get('layers') or [])]
                            for key, material in scene['materials'].items() if isinstance(material, dict)}
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(ENGINE))
        panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    save()
    QtCore.QTimer.singleShot(40000 if ENGINE == 'moonray' else 22000, finish)


def finish():
    panel = panel_widget()
    result['status'] = panel.status.text()
    result['notices'] = (panel.renderer.active or {}).get('snapshot', {}).get('warnings')
    panel.preview.image.save(str(out / (tag + '.png')))
    save()
    panel.stop()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


try:
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    for environment in modo.Scene().items('environment'):
        environment.channel('radiance').set(0.0)
    lx.eval('shader.create %s' % KIND)
    layer = [item for item in modo.Scene().items('textureLayer') if item.type == KIND][-1]
    # In a material of the ball's own, as an artist has it.
    ball = [item for item in modo.Scene().items('mesh')][-1]
    lx.eval('select.item {%s} set' % ball.id)
    lx.eval('select.typeFrom polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial Ball {0.8 0.8 0.8} 0.8 0.04 true false')
    lx.eval('select.typeFrom item')
    mask = next(item for item in modo.Scene().items('mask') if 'Ball' in item.name)
    lx.eval('texture.parent {%s} 2 item:{%s}' % (mask.id, layer.id))
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('shader.setEffect diffColor')
    result['layer'] = [layer.name, layer.channel('effect').get(), layer.parent.name if layer.parent else None]
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['setup_error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
