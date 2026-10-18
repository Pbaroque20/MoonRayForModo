# python
"""Isolated GUI test: Modo's resolution gate in the viewport, looking through Modo's cameras and MoonRay's.

The viewport is pictured looking through: Modo's render camera, a second Modo camera, a MoonRay perspective camera,
and that camera once it is the render camera. Each picture is test-results/camera-gate/<n>.png; the gate shows as the
frame drawn around the part of the view that renders."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/camera-gate'
out.mkdir(parents=True, exist_ok=True)
result = {'views': {}}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def window_picture(file):
    QtWidgets.QApplication.processEvents()
    shown = sorted((w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()), key=lambda w: -w.width() * w.height())
    if shown:
        shown[0].grab().save(str(out / file))


def look(label, key, render=False):
    def step():
        item = held[key]
        if render:
            lx.eval('render.camera {%s}' % item.id)
        lx.eval('select.drop item')
        lx.eval('view3d.projection cam')
        lx.eval('view3d.cameraItem {%s}' % item.id)
        result['views'][label] = {'camera': lx.eval('view3d.cameraItem ?'), 'render_camera': modo.Scene().renderCamera.name,
                                  'lens': {c: item.channel(c).get() for c in ('focalLen', 'apertureX', 'apertureY', 'filmFit', 'resOverride')}}
        QtCore.QTimer.singleShot(2500, lambda: window_picture(label + '.png'))
    return step


def perspective():
    # An ordinary perspective view: the MoonRay camera's gate is drawn, but nothing is dimmed.
    lx.eval('view3d.projection psp')
    result['views']['5_perspective'] = {'camera': lx.eval('view3d.cameraItem ?')}
    QtCore.QTimer.singleShot(2500, lambda: window_picture('5_perspective.png'))
    # The test Modo keeps its layout: the viewport is put back to looking through a camera.
    QtCore.QTimer.singleShot(3000, lambda: lx.eval('view3d.projection cam'))


def run(steps, index=0):
    if index >= len(steps):
        save()
        lx.eval('!app.quit')
        return
    function, wait = steps[index]
    try:
        function()
    except Exception:
        result.setdefault('errors', []).append(traceback.format_exc())
    save()
    QtCore.QTimer.singleShot(wait, lambda: run(steps, index + 1))


try:
    scene = modo.Scene()
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    held['render'] = scene.renderCamera
    lx.eval('item.create camera')
    held['second'] = scene.selected[-1]
    lx.eval('moonray.entity.add PerspectiveCamera')
    held['moonray'] = scene.selected[-1]
    for key in ('render', 'second', 'moonray'):
        lx.eval('select.item {%s} set' % held[key].id)
        lx.eval('transform.channel pos.Z 4.0')
        lx.eval('transform.channel pos.Y 0.0')
        lx.eval('transform.channel rot.X 0.0')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(6000, lambda: run([(look('1_modo_render_camera', 'render'), 4000), (look('2_modo_second_camera', 'second'), 4000),
                                            (look('3_moonray_camera', 'moonray'), 4000), (look('4_moonray_render_camera', 'moonray', True), 4000), (perspective, 4000)]))
