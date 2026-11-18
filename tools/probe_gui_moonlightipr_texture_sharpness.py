# python
"""GUI check of MoonLightIPR's Render textures: the 9Spheres test scene (images of 2048 pixels) at 960 x 540, rendered
three ways, each saved as the preview shows it: a MoonLightIPR Render (RT off, at the camera's resolution, every image at
its full size), MoonLightIPR's realtime (images kept small, 512 here), and MoonRay. How sharp each is is measured
afterwards, outside Modo, from test-results/moonlightipr-texture-sharpness. Writes report.json there.

PROBE_SCENE names another scene, PROBE_RES another size (960x540 unless named), PROBE_OUT another folder."""
import json
import os
import pathlib
import shutil
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = pathlib.Path(os.environ.get('PROBE_OUT', str(root / 'test-results/moonlightipr-texture-sharpness')))
shutil.rmtree(out, ignore_errors=True)
out.mkdir(parents=True, exist_ok=True)
SCENE = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\9Spheres_test_16_1\9Spheres_test_16_1_bundled.lxo')
result = {'scene': SCENE}
held = {}


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


def setup():
    lx.eval('!scene.open {%s} normal' % SCENE)
    render = modo.Scene().renderItem
    result['scene size'] = (render.channel('resX').get(), render.channel('resY').get())
    width, height = (int(v) for v in os.environ.get('PROBE_RES', '960x540').split('x'))
    render.channel('resX').set(width)
    render.channel('resY').set(height)
    lx.eval('moonray.page preview')
    later(8000, start)


def panel():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def start():
    p = panel()
    held['camera_resolution'] = p.preferences.get('moonlightipr/camera_resolution')
    p.preferences.store.setValue('moonlightipr/camera_resolution', True)
    if p.ipr_mode.isChecked():
        p.ipr_mode.setChecked(False)
    p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonlightipr'))
    later(1500, lambda: render('moonlightipr_render', after=realtime))


def render(name, after):
    held['name'], held['after'], held['tries'] = name, after, 0
    panel().render_once()
    later(1000, wait)


def wait():
    p = panel()
    held['tries'] += 1
    if p._rendering and held['tries'] < 2400:
        later(500, wait)
        return
    later(1500, lambda: keep(held['name'], held['after']))


def keep(name, after):
    p = panel()
    image = p.preview.image
    image.save(str(out / (name + '.png')))
    result[name] = {'size': (image.width(), image.height()), 'label': p.image_info.text(), 'status': p.status.text(), 'seconds': held['tries'] * 0.5}
    save()
    after()


def realtime():
    p = panel()
    p.ipr_mode.setChecked(True)
    held['tries'] = 0
    later(2000, realtime_wait)


def realtime_wait():
    p = panel()
    held['tries'] += 1
    # Realtime gathers its RT pixel samples (256) in a few seconds here: 15 s.
    if held['tries'] < 30:
        later(500, realtime_wait)
        return
    later(1000, lambda: keep('moonlightipr_realtime', moonray))


def moonray():
    p = panel()
    p.ipr_mode.setChecked(False)
    p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonray'))
    later(2000, lambda: render('moonray', after=finish))


def finish():
    if held.get('finished'):
        return
    held['finished'] = True
    try:
        p = panel()
        if p.ipr_mode.isChecked():
            p.ipr_mode.setChecked(False)
        if held.get('camera_resolution') is not None:
            p.preferences.store.setValue('moonlightipr/camera_resolution', held['camera_resolution'])
    except Exception:
        result.setdefault('errors', []).append('finish: ' + traceback.format_exc())
    result['done'] = True
    save()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


save()
guarded(setup)()
