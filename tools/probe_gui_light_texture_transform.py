# python
"""GUI check of a light's picture laid as MoonRay lays it: four MoonRay RectLights facing the camera, seen by it, each
with the same four-colour picture (red top left, green top right, blue bottom left, white bottom right) and its own
texture settings: as they are (1), Texture Reps U 2 and V 3 (2), Reps 2 and 2 with Mirror U (3), and Rotation 30,
Translation 0.25 0, Coverage 0.5 1 with a purple border (4). Rendered with MoonRay XPU, MoonRay XPU2 and MoonLightIPR (a Render),
each saved; they are compared afterwards, outside Modo. Writes test-results/light-texture-transform/report.json."""
import json
import os
import pathlib
import shutil
import traceback
import lx
import modo
from PySide2 import QtCore, QtGui, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / ('test-results/light-texture-transform' + os.environ.get('PROBE_TAG', ''))
shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True, exist_ok=True)
result = {'runs': {}}
held = {'to do': [e for e in os.environ.get('PROBE_ENGINES', 'xpu,xpu2,moonlightipr').split(',') if e]}
VARIANTS = (
    {},
    {'texture_reps_u': 2.0, 'texture_reps_v': 3.0},
    {'texture_reps_u': 2.0, 'texture_reps_v': 2.0, 'texture_mirror_u': True},
    {'texture_rotation': 30.0, 'texture_translation': (0.25, 0.0), 'texture_coverage': (0.5, 1.0), 'texture_border_color': (0.4, 0.0, 0.4)},
)
PLACES = ((-1.05, 1.05), (1.05, 1.05), (-1.05, -1.05), (1.05, -1.05))
TURNED = (0, 3.14159265358979, 0)
SIZE = {'width': 2.0, 'height': 2.0}
# PROBE_SET: 'rect' (the four settings above, on RectLights), 'kinds' (the other local lights as they are, then with Reps
# 2 and 2: a disc, a sphere, a cylinder and a spot) or 'distant' (a DistantLight's disc, 24 degrees across, as it is).
SET = os.environ.get('PROBE_SET', 'rect')
if SET == 'kinds':
    LIGHTS = [('DiskLight', place, {'radius': 1.0}, TURNED) for place in PLACES[:1]] +              [('SphereLight', PLACES[1], {'radius': 0.95}, (0, 0, 0)),
              ('CylinderLight', PLACES[2], {'radius': 0.5, 'height': 1.9}, TURNED),
              ('SpotLight', PLACES[3], {'lens_radius': 0.95, 'outer_cone_angle': 120.0, 'inner_cone_angle': 100.0}, TURNED)]
    if os.environ.get('PROBE_REPS'):
        LIGHTS = [(k, p, dict(s, texture_reps_u=2.0, texture_reps_v=2.0), r) for k, p, s, r in LIGHTS]
elif SET == 'distant':
    LIGHTS = [('DistantLight', (0.0, 0.0), {'angular_extent': 24.0}, TURNED)]
else:
    LIGHTS = [('RectLight', place, dict(SIZE, **variant), TURNED) for variant, place in zip(VARIANTS, PLACES)]


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def guarded(step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            finish()
        save()
    return run


def later(ms, step):
    QtCore.QTimer.singleShot(ms, guarded(step))


def picture():
    """The four-colour picture, 256 pixels a side, as a PNG beside the report."""
    image = QtGui.QImage(256, 256, QtGui.QImage.Format_RGB32)
    for x0, y0, colour in ((0, 0, (255, 0, 0)), (128, 0, (0, 255, 0)), (0, 128, (0, 0, 255)), (128, 128, (255, 255, 255))):
        for y in range(y0, y0 + 128):
            for x in range(x0, x0 + 128):
                image.setPixelColor(x, y, QtGui.QColor(*colour))
    path = out / 'quadrants.png'
    image.save(str(path))
    return path


def setup():
    from moonray_modo import entities
    path = picture()
    scene = modo.Scene()
    # MoonRay takes its lights from the light sets of the geometry in its layer: a small cube behind the camera.
    mesh = scene.addMesh('Behind')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.reset')
    for axis, value in (('cenX', 0), ('cenY', 0), ('cenZ', 20), ('sizeX', .1), ('sizeY', .1), ('sizeZ', .1)):
        lx.eval('tool.attr prim.cube %s %s' % (axis, value))
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.cube off')
    for name, value in (('resX', 400), ('resY', 400)):
        scene.renderItem.channel(name).set(value)
    modo.LocatorSuperType(scene.renderCamera).position.set((0, 0, 7))
    modo.LocatorSuperType(scene.renderCamera).rotation.set((0, 0, 0))
    for kind, (x, y), variant, turn in LIGHTS:
        before = {item.id for item in entities.items_of(scene, kind)}
        lx.eval('moonray.entity.add ' + kind)
        light = next(item for item in entities.items_of(scene, kind) if item.id not in before)
        locator = modo.LocatorSuperType(light)
        locator.position.set((x, y, 0))
        # Turned to face the camera: the flat lights, the spot and the distant light shine along their own -Z.
        locator.rotation.set(turn)
        settings = {'texture': str(path), 'normalized': False, 'intensity': 1.0, 'visible_in_camera': 1}
        settings.update(variant)
        for key, value in settings.items():
            channel = 'mr_' + key
            if isinstance(value, (tuple, list)):
                suffixes = ('.R', '.G', '.B') if key.endswith('color') else ('.X', '.Y')
                for suffix, part in zip(suffixes, value):
                    light.channel(channel + suffix).set(part)
            else:
                light.channel(channel).set(value)
        from moonray_modo.host import world_matrix
        placed = [float(v) for v in world_matrix(light)]
        result.setdefault('lights', []).append({'name': light.name, 'place': (x, y), 'settings': settings,
                                                'rotation read': [float(v) for v in locator.rotation.get()], 'z axis': placed[8:11]})
    lx.eval('moonray.page preview')
    later(3000, next_run)


def panel():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def next_run():
    p = held['panel'] = panel()
    if not held['to do']:
        finish()
        return
    engine = held['now'] = held['to do'].pop(0)
    if engine != 'moonlightipr':
        held.setdefault('renderer_kept', p.preferences.get('xpu2/renderer'))
        p.preferences.set('xpu2/renderer', engine)
    p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr' if engine == 'moonlightipr' else 'moonray'))
    later(1500, start)


def start():
    held['panel'].render_once()
    later(1000, lambda: wait(600))


def wait(tries):
    if held['panel']._rendering and tries > 0:
        later(500, lambda: wait(tries - 1))
    else:
        later(2000, finished)


def finished():
    p = held['panel']
    image = p.preview.image
    if not image.isNull():
        image.save(str(out / (held['now'] + '.png')))
    result['runs'][held['now']] = {'status': p.status.text(), 'label': p.image_info.text(), 'size': (image.width(), image.height()),
                                   'notices': [line for line in p.renderer.log.splitlines() if 'texture' in line.lower()][:6]}
    (out / (held['now'] + '.log')).write_text(p.renderer.log, encoding='utf-8')
    save()
    later(1500, next_run)


def finish():
    if held.get('finished'):
        return
    held['finished'] = True
    try:
        if 'renderer_kept' in held:
            panel().preferences.set('xpu2/renderer', held['renderer_kept'] or 'xpu2')
    except Exception:
        result.setdefault('errors', []).append('finish: ' + traceback.format_exc())
    result['done'] = True
    save()
    QtCore.QTimer.singleShot(1000, lambda: lx.eval('!app.quit'))


save()
# Scene edits here, at the probe's top level: Modo refuses them from a Qt timer.
guarded(setup)()
