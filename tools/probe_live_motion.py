# python
"""Isolated GUI test: motion blur while MoonLightIPR follows the scene.

A MoonRay sphere is keyed to cross the view in one frame, and the time set between its keys. The preview follows the
scene in MoonLightIPR with motion blur on (the default). Each update it sends is written down: whether it carries the
shutter, and whether the sphere moves in it. Then a light is moved, as an edit let go, and the next update looked at.
The preview is pictured after each."""
import json
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/live-motion'
out.mkdir(parents=True, exist_ok=True)
result = {'updates': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin():
    try:
        panel = held['panel'] = panel_widget()
        panel.preferences.set('runtime', 'C:/Users/Raphael Tobar/AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime')
        # The test settings may hold an earlier probe's choice; the user's default is on.
        panel.preferences.set('preview_motion', True)
        result['motion_preference'] = panel.preferences.get('preview_motion')
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
        QtWidgets.QApplication.processEvents()
        submit = panel.renderer.submit

        def watched(scene, *a, **k):
            sphere = next((e for e in scene.get('entities', []) if e.get('class') == 'SphereGeometry'), {})
            result['updates'].append({'at': round(time.time() - held['began'], 1), 'shutter': scene.get('motion_steps'),
                                      'sphere_moves': bool(sphere.get('matrix_close')) and sphere.get('matrix_close') != sphere.get('matrix'),
                                      'phase': held.get('phase'),
                                      'from': [f'{frame.name}:{frame.lineno}' for frame in traceback.extract_stack()[-6:-1]]})
            return submit(scene, *a, **k)
        panel.renderer.submit = watched
        held['began'] = time.time(); held['phase'] = 'following'
        panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(20000, edit)


def picture(name):
    try:
        held['panel'].preview.grab().save(str(out / name))
    except Exception:
        result.setdefault('picture_errors', []).append(traceback.format_exc())


def edit():
    try:
        picture('1_following.png')
        held['phase'] = 'after moving a light'
        light = next(iter(modo.Scene().items('light', superType=True)))
        lx.eval('select.item {%s} set' % light.id)
        lx.eval('transform.channel pos.Y %f' % (modo.LocatorSuperType(light).position.y.get() + 0.5))
        result['moved_light'] = light.name
    except Exception:
        result['error2'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(20000, sharp)


def sharp():
    try:
        picture('2_after_edit.png')
        # The same, with motion blur off: a light nudged so the preview updates.
        held['panel'].preferences.set('preview_motion', False)
        held['phase'] = 'motion blur off'
        light = next(iter(modo.Scene().items('light', superType=True)))
        lx.eval('select.item {%s} set' % light.id)
        lx.eval('transform.channel pos.Y %f' % (modo.LocatorSuperType(light).position.y.get() - 0.5))
    except Exception:
        result['error4'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(15000, finish)


def finish():
    try:
        picture('3_sharp.png')
        result['status'] = held['panel'].status.text()
        held['panel'].stop()
    except Exception:
        result['error3'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1000, lambda: lx.eval('!app.quit'))


try:
    scene = modo.Scene()
    lx.eval('moonray.entity.add SphereGeometry')
    sphere = next(i for i in scene.items() if 'Sphere' in i.name and i.type != 'mesh')
    result['sphere'] = sphere.name
    fps = scene.fps
    placed = modo.LocatorSuperType(sphere)
    placed.position.x.set(-1.5, time=12.0 / fps, key=True)
    placed.position.x.set(1.5, time=13.0 / fps, key=True)
    lx.service.Selection().SetTime(12.5 / fps)
except Exception:
    result['setup_error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(6000, begin)
