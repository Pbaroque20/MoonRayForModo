# python
"""GUI: a Backplate's photo in the viewport (backplate_viewport.py, moonray.backplate.viewport). A new scene, a cube, the
render camera 6 m back; a Backplate added as the MoonRay menu adds it and given a photo (PROBE_IMAGE). Then, a second or
two apart: looking through the camera (picture), "backplate in the viewport" off (its Backdrop should go), on again
(back), another photo (PROBE_IMAGE2: the Backdrop's photo should change), the Backplate deleted (the Backdrop goes too).
At each step: the kit's Backdrops (owner and photo tags) and any fault. Writes test-results/backplate-viewport-gui/.
Run with tools/launch_gui_probe.py probe_gui_backplate_viewport.py --show."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\backplate-viewport-gui'))
out.mkdir(parents=True, exist_ok=True)
ROOT = r'C:\Users\Raphael Tobar\MoonRayForModo'
IMAGE = os.environ.get('PROBE_IMAGE', ROOT + r'\docs\images\shadow-catcher.png')
IMAGE2 = os.environ.get('PROBE_IMAGE2', ROOT + r'\docs\images\glass-alpha.png')
report = {'stages': [], 'errors': []}
state = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def later(fn, wait=2500):
    def run():
        try:
            fn()
        except Exception:
            report['errors'].append(traceback.format_exc())
            finish()
    QtCore.QTimer.singleShot(wait, run)


def picture(name):
    shown = [w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QMainWindow) and w.isVisible()]
    window = max(shown, key=lambda w: w.width() * w.height(), default=None)
    if window is not None:
        QtGui.QGuiApplication.primaryScreen().grabWindow(window.winId()).save(str(out / (name + '.png')))


def stage(name, shot=False):
    import modo
    from moonray_modo import backplate_viewport, entities
    scene = modo.Scene()
    backdrops = []
    for item in scene.items():
        if item.type == 'backdrop':
            backdrops.append({'id': item.id, 'name': item.name, 'owner': backplate_viewport._tag(item, backplate_viewport.OWNER),
                              'photo': backplate_viewport._tag(item, backplate_viewport.SHOWN),
                              'parent': item.parent.id if item.parent else None,
                              'projection': item.channel('projection').get(), 'pixelSize': item.channel('pixelSize').get(), 'hidePersp': item.channel('hidePersp').get(),
                              'z': _z(item)})
    report['stages'].append({'stage': name, 'backdrops': backdrops, 'selected': [i.id for i in scene.selected],
                             'lacking': backplate_viewport.lacking(scene), 'faults': dict(entities.DRAW_FAULTS)})
    if shot:
        picture(name)
    save()


def _z(item):
    try:
        import modo
        return modo.LocatorSuperType(item).position.z.get()
    except Exception as exc:
        return repr(exc)


def channel(key, value):
    lx.eval('select.item {%s} set' % state['plate'])
    lx.eval('item.channel moonray.BackplateEnvironment$mr_%s %s' % (key, value))


def through_camera():
    lx.eval('view3d.projection cam')
    later(lambda: (stage('photo, through the camera', True), off()), 3000)


def off():
    channel('viewport_plate', 'false')
    later(lambda: (stage('viewport off', True), on()))


def on():
    channel('viewport_plate', 'true')
    later(lambda: (stage('viewport on again'), card()))


def card():
    channel('backdrop_distance', '3.0')
    later(lambda: (stage('distance 3 m, through the camera', True), card_perspective()))


def card_perspective():
    lx.eval('view3d.projection psp')
    try:
        lx.eval('viewport.fit')
    except Exception:
        report['errors'].append('viewport.fit: ' + traceback.format_exc()[-200:])
    later(lambda: (stage('distance 3 m, perspective', True), lens()), 3000)


def lens():
    import modo
    lx.eval('view3d.projection cam')
    lx.eval('select.item {%s} set' % modo.Scene().renderCamera.id)
    lx.eval('item.channel camera$focalLen 0.035')
    later(lambda: (stage('35 mm lens'), behind()))


def behind():
    channel('backdrop_distance', '0.0')
    later(lambda: (stage('distance 0 again'), other()))


def other():
    channel('plate', '{%s}' % IMAGE2)
    later(lambda: (stage('another photo', True), undone()))


def undone():
    lx.eval('app.undo')
    later(lambda: (stage('photo change undone'), deleted()))


def deleted():
    lx.eval('select.item {%s} set' % state['plate'])
    lx.eval('!item.delete')
    later(lambda: (stage('backplate deleted'), finish()))


def finish():
    save()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


try:
    import modo
    lx.eval('scene.new')
    scene = modo.Scene()
    camera = scene.renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    lx.eval('transform.channel pos.Y 1.6'); lx.eval('transform.channel pos.Z 6.0')
    lx.eval('moonray.entity.add BackplateEnvironment')
    plate = [i for i in scene.items() if i.type == 'moonray.BackplateEnvironment'][0]
    state['plate'] = plate.id
    report['plate'] = plate.id
    later(lambda: (stage('added, no photo'), given()), 2000)

    def given():
        channel('plate', '{%s}' % IMAGE)
        later(lambda: (stage('photo given'), through_camera()))
except Exception:
    report['errors'].append(traceback.format_exc())
    save()
save()
