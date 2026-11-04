# python
"""Isolated GUI test: a dw PerspectiveCamera rendering through XPU2 with depth of field and a bokeh image, as an artist sets
it up (MOONRAY_PROBE_BOKEH, an image file; the Modo lens on, Modo's depth of field and Iris Blades as given). The preview
is rendered with XPU2 chosen in XPU mode; every status said is written down, so that one leaving the scene to MoonRay XPU
says why; and the scene the session was handed is kept. Writes test-results/bokeh-xpu2/report.json and pictures."""
import json
import os
import pathlib
import shutil
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/bokeh-xpu2'
out.mkdir(parents=True, exist_ok=True)
image = os.environ.get('MOONRAY_PROBE_BOKEH', '')
blades = int(os.environ.get('MOONRAY_PROBE_BLADES', '0'))
result = {'image': image, 'blades': blades, 'status': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin():
    try:
        from moonray_modo import entities
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.cube on')
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
        scene = modo.Scene()
        lx.eval('moonray.entity.add PerspectiveCamera')
        camera = next(i for i in scene.selected if i.type == 'camera')
        lx.eval('render.camera {%s}' % camera.id)
        # As the forms set them: Modo's item.channel command on the selected camera.
        lx.eval('select.item {%s} set' % camera.id)
        for name, value in (('dof', 'true'), ('fStop', '1.4'), ('focusDist', '2.0'), ('irisBlades', str(blades))):
            try:lx.eval('item.channel camera$%s %s' % (name, value))
            except Exception as exc:result.setdefault('set_errors', {})[name] = str(exc)
        if image:
            # As the dw tab's bokeh image chooser does: its command, the file dialog answered with the image.
            try:
                i = entities.classes().index('PerspectiveCamera')
                j = [key for key, *_ in entities.channels('PerspectiveCamera')].index('bokeh_image')
                modo.dialogs.customFile = lambda *a, **k: image
                lx.eval('moonray.entity.option%d_%d 99' % (i, j))
            except Exception as exc:result.setdefault('set_errors', {})['bokeh_image'] = str(exc)
        result['channels'] = {name: camera.channel(name).get() for name in ('dof', 'fStop', 'focusDist', 'irisBlades', entities.CHANNEL_PREFIX + 'bokeh_image')}
        result['camera_params'] = {k: v for k, v in next(e for e in __import__('moonray_modo.host', fromlist=['x']).snapshot()['entities']
                                                         if e['identity'] == camera.id)['parameters'].items() if 'bokeh' in k or k.startswith('dof')}
        lx.eval('moonray.open')
        QtWidgets.QApplication.processEvents()
        panel = held['panel'] = panel_widget()
        panel.preferences.set('xpu2/renderer', 'xpu2')
        panel._store(execution_mode='xpu')
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        panel.start.click()
        QtCore.QTimer.singleShot(1000, lambda: watch(0))
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


def watch(seconds):
    panel = held['panel']
    said = panel.status.text()
    if said and (not result['status'] or result['status'][-1] != said):result['status'].append(said)
    if (panel._rendering or seconds < 5) and seconds < 120:
        QtCore.QTimer.singleShot(1000, lambda: watch(seconds + 1));return
    try:
        session = getattr(panel.renderer, 'session', None)
        result['xpu2_active'] = getattr(session, 'xpu2_active', None)
        result['xpu2_refused'] = getattr(session, 'xpu2_refused', None)
        result['info'] = panel.image_info.text()
        # The scene the session was handed, for reading what it said of the camera.
        active = panel.renderer.active or {}
        for path in pathlib.Path(panel.renderer.directory.name).glob('*.rdla'):
            shutil.copyfile(str(path), str(out / path.name))
        result['kept_scenes'] = sorted(p.name for p in out.glob('*.rdla'))
        panel.window().grab().save(str(out / 'window.png'))
    except Exception:
        result['watch_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(800, lambda: lx.eval('!app.quit'))


result['started'] = True
save()
QtCore.QTimer.singleShot(5000, begin)
