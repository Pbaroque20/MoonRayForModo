# python
"""Isolated GUI test: MoonRay's cameras as Modo cameras, which Modo's viewport lists and looks through.

A sphere and one of each MoonRay camera with a view are made. Noted: whether each is among the scene's cameras, its
Modo lens as evaluated (focal length, film, projection, film fit) beside what entities.modo_lens says it should be,
the lens again after the perspective camera's MoonRay focal length is changed, whether the viewport can be set to look
through it, and which camera a MoonRay scene is rendered through once it is Modo's render camera. Modo's main window
is pictured looking through the perspective camera and the orthographic one."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/viewport-cameras'
out.mkdir(parents=True, exist_ok=True)
result = {'cameras': {}}
held = {}
LENS = ('focalLen', 'apertureX', 'offsetX', 'offsetY', 'projType', 'filmFit', 'target')


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def lens(item):
    found = {}
    for name in LENS:
        try:
            found[name] = item.channel(name).get()
        except Exception as exc:
            found[name] = 'error: %s' % exc
    return found


def expected(name, item):
    from moonray_modo import entities
    values = {key: float(item.channel(entities.CHANNEL_PREFIX + key).get()) for key in entities.lens_inputs(name)}
    return entities.modo_lens(name, lambda key: values[key], float(item.channel('target').get()))


def window_picture(file):
    shown = sorted((w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()), key=lambda w: -w.width() * w.height())
    if shown:
        # The viewport's own picture may lag behind in the grab; the camera menu's label shows which camera it is.
        shown[0].grab().save(str(out / file))


def read():
    from moonray_modo import entities
    scene = modo.Scene()
    listed = {item.id for item in scene.items('camera')}
    for name, item in held.items():
        result['cameras'][name] = {'type': item.type, 'among_cameras': item.id in listed, 'lens': lens(item), 'expected': expected(name, item)}


def change_focal():
    for name, channel, value in (('PerspectiveCamera', 'mr_focal', 60.0), ('OrthographicCamera', 'mr_film_width_aperture', 6.0)):
        lx.eval('select.item {%s} set' % held[name].id)
        lx.eval('item.channel %s %s' % (channel, value))


def reread():
    for name in ('PerspectiveCamera', 'OrthographicCamera'):
        item = held[name]
        result['cameras'][name]['after_change'] = {'lens': lens(item), 'expected': expected(name, item)}


def look(name, file):
    def step():
        item = held[name]
        try:
            lx.eval('select.item {%s} set' % item.id)
            lx.eval('view3d.cameraItem {%s}' % item.id)
            result.setdefault('looked_through', {})[name] = lx.eval('view3d.cameraItem ?')
        except Exception as exc:
            result.setdefault('looked_through', {})[name] = 'error: %s' % exc
        QtWidgets.QApplication.processEvents()
        QtCore.QTimer.singleShot(1500, lambda: window_picture(file))
    return step


def render_camera():
    from moonray_modo import host, camera_choice
    scene = modo.Scene()
    lx.eval('render.camera {%s}' % held['PerspectiveCamera'].id)
    snapshot = host.snapshot()
    rendered = [e['name'] for e in snapshot.get('entities', []) if e.get('parameters', {}).get('modo_render_camera')]
    result['render_camera'] = {'modo_render_camera': scene.renderCamera.name, 'rendered_through': rendered,
                               'choice_current': camera_choice.current() == held['PerspectiveCamera'].id,
                               'warnings': snapshot.get('warnings', [])[:6]}


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
    from moonray_modo import entities
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    for name in entities.VIEWED_CAMERAS:
        lx.eval('moonray.entity.add {%s}' % name)
        item = modo.Scene().selected[-1]
        held[name] = item
        result.setdefault('made', {})[name] = [item.type, type(item).__name__]
        lx.eval('transform.channel pos.Z 5.0')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(6000, lambda: run([(read, 500), (change_focal, 500), (reread, 500), (look('PerspectiveCamera', 'perspective.png'), 3000),
                                            (look('OrthographicCamera', 'orthographic.png'), 3000), (render_camera, 500)]))
