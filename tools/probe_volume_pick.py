# python
"""GUI: Select Volume Here. A test VDB (modo_vdb_grid --ball: a ball of fog 2.35 across with a hole off to one side) made
as Load VDB File makes it, the camera 6 units back looking at it; one MoonLightIPR Render so the preview has a picture;
then the picker over an 11 x 11 grid of points of the picture (what it finds at each), and the menu's own action at
the middle and at a corner, with what Modo then has selected and what the status line says. Writes
test-results/volume-pick/report.json and picture.png."""
import json
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\volume-pick')
result = {}
state = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def build():
    from moonray_modo import entities
    scene = modo.Scene()
    prefix = entities.CHANNEL_PREFIX
    shape = scene.addItem(entities.item_type('VdbGeometry'), name='Ball')
    volume = scene.addItem(entities.item_type('VdbVolume'), name='BallFog')
    for key, value in (('model', str(out / 'ball.vdb').replace('\\', '/')), ('density_grid', 'density'), ('modo_volume', volume.name)):
        shape.channel(prefix + key).set(value)
    camera = scene.renderCamera
    camera.position.set((0.0, 0.0, 6.0))
    camera.rotation.set((0.0, 0.0, 0.0))
    result['items'] = [shape.name, shape.id, volume.name, camera.name]
    state['shape'] = shape.id


def begin():
    try:
        p = panel()
        result['kept_samples'] = p.preferences.get('moonlightipr/render_samples')
        p.preferences.set('moonlightipr/render_samples', 16)
        p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
        state['began'] = time.monotonic()
        QtCore.QTimer.singleShot(1500, lambda: (p.start.click(), QtCore.QTimer.singleShot(1000, rendered)))
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def rendered():
    p = panel()
    # Until the picture is shown (its label filled): the menu's action works on the picture's area.
    shown = bool(p.image_info.text()) and not p.preview.image_rect().isEmpty()
    if (getattr(p, '_rendering', False) or not getattr(p, '_asset_scene', None) or not shown) and time.monotonic() - state['began'] < 180:
        QtCore.QTimer.singleShot(500, rendered); return
    result['render_seconds'] = round(time.monotonic() - state['began'], 1)
    result['label'] = p.image_info.text()
    p.preview.image.save(str(out / 'picture.png'))
    state['tries'] = 0
    probe()


def probe():
    """The picker over the grid; the coarse grid is read in the background on first use, so it is asked again."""
    try:
        p = panel()
        from moonray_modo.volume_pick import volume_at
        scene = p._asset_scene
        rows = []
        waiting = False
        for j in range(11):
            row = ''
            for i in range(11):
                found = volume_at(scene, (i + 0.5) / 11, (j + 0.5) / 11)
                if found[0] is None and found[1]:
                    waiting = True
                row += '#' if found[0] is not None else '.'
            rows.append(row)
        state['tries'] += 1
        if waiting and state['tries'] < 40:
            QtCore.QTimer.singleShot(500, probe); return
        result['grid'] = rows
        result['grid_tries'] = state['tries']
        menu_actions()
    except Exception:
        result['error'] = traceback.format_exc(); finish()


def menu_actions():
    try:
        p = panel()
        rect = p.preview.image_rect()
        result['menu'] = {}
        for label, (u, v) in (('middle', (0.5, 0.5)), ('corner', (0.03, 0.03))):
            lx.eval('select.drop item')
            point = QtCore.QPoint(int(rect.left() + u * rect.width()), int(rect.top() + v * rect.height()))
            p.volume_at(point)
            result['menu'][label] = {'status': p.status.text(), 'selected': [i.name for i in modo.Scene().selected]}
        names = [a.text() for a in menu_texts(p)]
        result['menu_has_entry'] = 'Select Volume Here' in names
    except Exception:
        result['menu_error'] = traceback.format_exc()
    finish()


def menu_texts(p):
    """The entries of the picture's right-click menu, made as a right-click makes it (_image_menu returns it unshown)."""
    rect = p.preview.image_rect()
    menu = p._image_menu(QtCore.QPoint(int(rect.center().x()), int(rect.center().y())))
    found = list(menu.actions())
    menu.deleteLater()
    return found


def finish():
    try:
        panel().preferences.set('moonlightipr/render_samples', result.get('kept_samples') or 2000)
    except Exception:
        pass
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


try:
    build()
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
