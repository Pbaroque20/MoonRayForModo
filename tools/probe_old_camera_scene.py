# python
"""Isolated GUI test: a scene saved with MoonRay camera items, loaded again.

MOONRAY_PROBE_STEP=save makes a perspective and an orthographic MoonRay camera (focal length 45, film width 7) and
saves test-results/viewport-cameras/old_cameras.lxo; MOONRAY_PROBE_STEP=load opens it and notes each item's type,
whether it is among the scene's cameras, its MoonRay values and its Modo lens. Run save with the kit as it was and load
with the kit as it is, to see that scenes from before MoonRay's cameras were Modo cameras still load."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/viewport-cameras'
out.mkdir(parents=True, exist_ok=True)
scene_file = out / 'old_cameras.lxo'
step = os.environ.get('MOONRAY_PROBE_STEP', 'save')
result = {'step': step}
try:
    if step == 'save':
        for name, channel, value in (('PerspectiveCamera', 'mr_focal', 45.0), ('OrthographicCamera', 'mr_film_width_aperture', 7.0)):
            lx.eval('moonray.entity.add {%s}' % name)
            lx.eval('item.channel %s %s' % (channel, value))
        lx.eval('!scene.saveAs {%s} $LXOB false' % scene_file)
        result['saved'] = scene_file.is_file()
    else:
        lx.eval('!scene.open {%s} normal' % scene_file)
except Exception:
    result['error'] = traceback.format_exc()


def read():
    # After the scene has loaded and its MoonRay cameras of the type from before have been made Modo cameras.
    from moonray_modo import entities
    try:
        scene = modo.Scene()
        left = [item.id for item in scene.items() if item.type in ('moonray.PerspectiveCamera', 'moonray.OrthographicCamera')]
        result['left_after_loading'] = left
        if os.environ.get('MOONRAY_PROBE_UPGRADE'):
            # Made Modo cameras by the command itself, to tell a command that fails from one never called.
            for identity in left:
                try:
                    lx.eval('moonray.camera.upgrade {%s}' % identity)
                    result.setdefault('upgrade', []).append('ok')
                except Exception as exc:
                    result.setdefault('upgrade', []).append('error: %s' % exc)
            scene = modo.Scene()
        listed = {item.id for item in scene.items('camera')}
        result['items'] = {}
        for item in scene.items():
            if item.type.startswith('moonray.') or entities.class_of(item):
                values = {}
                for name in ('mr_focal', 'mr_film_width_aperture', 'focalLen', 'apertureX', 'projType'):
                    try:
                        values[name] = item.channel(name).get()
                    except Exception as exc:
                        values[name] = 'error: %s' % exc
                result['items'][item.name] = {'type': item.type, 'class': entities.class_of(item), 'among_cameras': item.id in listed, 'values': values}
    except Exception:
        result['read_error'] = traceback.format_exc()
    (out / ('old_scene_%s.json' % step)).write_text(json.dumps(result, indent=1, default=str))
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(3000 if step == 'load' else 1500, read)
