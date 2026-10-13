# python
"""Isolated GUI test: a texture layer straight under the Render item shows on polygons that carry no material tag.

A ball with no material set on it, and a chequered image as a bump layer under the Render item. What reading the
scene finds (the ball's material tags, the UV sets it carries, what the layers ask for) is written down, the scene is
rendered with MoonRay, and how much the ball's shading varies (which the bumps are what makes) is written down too."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/untagged-layer'
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def rough():
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


def begin():
    try:
        from moonray_modo import coordinates, host
        scene = host.snapshot(refresh_materials=True)
        result['materials'] = {key: [[layer.get('kind'), layer.get('effect'), layer.get('coordinate_key'), layer.get('uv_map')] for layer in (material.get('layers') or [])]
                               for key, material in scene['materials'].items() if isinstance(material, dict)}
        result['asked'] = sorted(coordinates.descriptors(scene['materials']))
        result['meshes'] = [[mesh.get('name'), mesh.get('material'), sorted(set(mesh.get('face_materials') or [])), sorted(mesh.get('uv_sets') or {}), len(mesh.get('uvs') or [])]
                            for mesh in scene['meshes']]
        result['warnings'] = scene['warnings']
        save()
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(os.environ.get('MOONRAY_PROBE_ENGINE', 'moonray')))
        panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    QtCore.QTimer.singleShot(30000, finish)


def finish():
    panel = panel_widget()
    result['status'] = panel.status.text()
    result['shading_varies_by'] = rough()
    result['log'] = sorted({line.strip()[:200] for line in str(getattr(panel.renderer, 'log', '') or '').splitlines() if 'unavailable' in line})[:4]
    panel.preview.image.save(str(out / 'picture.png'))
    save()
    panel.stop()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


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
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    for environment in modo.Scene().items('environment'):
        environment.channel('radiance').set(0.0)
    lx.eval('clip.addStill {%s}' % path.as_posix())
    lx.eval('texture.new clip:{cheques:videoStill001}')
    layer = next(iter(modo.Scene().items('imageMap')))
    lx.eval('texture.parent {%s} 2 item:{%s}' % (modo.Scene().renderItem.id, layer.id))
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('shader.setEffect bump')
    for material in modo.Scene().items('advancedMaterial'):
        lx.eval('channel.value 0.02 channel:{%s:bumpAmp}' % material.id)
    lx.eval('moonray.render.samples 3')
    lx.eval('moonray.open')
except Exception:
    result['setup_error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
