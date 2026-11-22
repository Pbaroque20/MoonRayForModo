# python
"""GUI: an Ocean Plane's waves in Modo's viewport (ocean_viewport.py). A new scene, an Ocean Plane added as the MoonRay
menu adds it and raised to PROBE_HEIGHT (1.0 m), the render camera 6 m up looking out to sea. Then, a few seconds apart:
the viewport as it opens, the viewport looking through the render camera (view3d.projection cam), and the timeline moved
to 2 s. At each: the main window's picture (taken off the screen: run with --show), and each plane's last drawing
(ocean_viewport.LAST: how many points, around which eye, at what moment, in how many ms) and any fault in drawing it
(entities.DRAW_FAULTS). Writes test-results/ocean-viewport-gui/report.json and the pictures (PROBE_OUT for another
folder). Run with tools/launch_gui_probe.py --show --kit-source <a kit with this adapter and modo_ocean.dll>."""
import json
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtGui, QtWidgets

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\ocean-viewport-gui'))
out.mkdir(parents=True, exist_ok=True)
report = {'stages': [], 'errors': []}
state = {'t0': time.monotonic()}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def later(fn, wait):
    def run():
        try:
            fn()
        except Exception:
            report['errors'].append(traceback.format_exc())
            finish()
    QtCore.QTimer.singleShot(wait, run)


def main_window():
    # Modo's own: the largest window showing (the kit's docked MoonShine Graph is a main window of its own too).
    shown = [w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, QtWidgets.QMainWindow) and w.isVisible()]
    return max(shown, key=lambda w: w.width() * w.height(), default=None)


def stage(name):
    from moonray_modo import entities, ocean_viewport
    window = main_window()
    if window is not None:
        # Off the screen, as it shows: the viewport's OpenGL drawing is not in a widget's own grab.
        screen = QtGui.QGuiApplication.primaryScreen()
        screen.grabWindow(window.winId()).save(str(out / (name + '.png')))
    import modo
    camera = modo.Scene().renderCamera
    rows = lx.object.Matrix(camera.channel('worldMatrix').get()).Get4()
    report['stages'].append({'stage': name, 'seconds': round(time.monotonic() - state['t0'], 1), 'camera_at': list(rows[3][:3]),
                             'scene_time': lx.service.Selection().GetTime(),
                             'drawn': {k: dict(v) for k, v in ocean_viewport.LAST.items()},
                             'faults': dict(entities.DRAW_FAULTS),
                             # Each viewport's drawings since the stage before: its eye and kind of view.
                             'viewports': sorted(set(ocean_viewport.DRAWS))})
    ocean_viewport.DRAWS.clear()
    save()


def opened():
    stage('opened')
    try:
        lx.eval('view3d.projection cam')
        report['camera_view'] = True
    except Exception:
        report['camera_view'] = traceback.format_exc()[-600:]
    later(through_camera, 4000)


def through_camera():
    stage('through the camera')
    lx.eval('select.time 2.0')
    later(moved_on, 4000)


def moved_on():
    stage('at 2 s')
    try:
        lx.eval('view3d.projection psp')
        report['perspective_view'] = True
    except Exception:
        report['perspective_view'] = traceback.format_exc()[-600:]
    later(in_perspective, 4000)


def in_perspective():
    stage('perspective')
    finish()


def finish():
    save()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


try:
    import modo
    lx.eval('scene.new')
    scene = modo.Scene()
    lx.eval('moonray.entity.add OceanPlaneGeometry')
    plane = [i for i in scene.items() if i.type == 'moonray.OceanPlaneGeometry'][0]
    lx.eval('select.item {%s} set' % plane.id)
    lx.eval('transform.channel pos.Y %s' % float(os.environ.get('PROBE_HEIGHT', '1.0')))
    report['plane'] = plane.id
    # PROBE_POINTS=0: the plane's Waves in the Viewport off, the rest the same (a quit without the points drawn).
    if os.environ.get('PROBE_POINTS', '1') == '0':
        lx.eval('item.channel moonray.OceanPlaneGeometry$mr_viewport_points false')
        report['points'] = False
    camera = scene.renderCamera
    lx.eval('select.item {%s} set' % camera.id)
    lx.eval('transform.channel pos.X 0.0')
    lx.eval('transform.channel pos.Y 6.0')
    lx.eval('transform.channel pos.Z 0.0')
    lx.eval('transform.channel rot.X -12.0')
    camera.channel('focalLen').set(0.035)
    lx.eval('select.drop item')
except Exception:
    report['errors'].append(traceback.format_exc())
save()
later(opened, 8000)
