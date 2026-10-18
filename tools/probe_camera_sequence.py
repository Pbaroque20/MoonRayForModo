# python
"""Isolated GUI test: the Camera Sequence.

Two cameras are made, Wide and Close, Close with a resolution of its own (640 x 480). They are keyed to frames 0-10 and
11-20 through the panel, as the window saves them. The scene is read at frames 5, 15 and 30: the camera each is read
through and its size are noted (Wide, Close at 640 x 480, and the render camera where no key covers the frame). A MoonRay
preview is rendered at frame 15 to see the render goes through. The Camera Sequence window is shown and pictured."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/camera-sequence'
out.mkdir(parents=True, exist_ok=True)
runtime = pathlib.Path.home() / 'AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
result = {'frames': {}}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def camera(name, x):
    lx.eval('item.create camera')
    item = modo.Scene().selected[-1]
    item.name = name
    item.position.x.set(x)
    item.position.z.set(4.0)
    return item


def keys():
    panel = panel_widget()
    wide, close = held['wide'], held['close']
    panel._store(camera_sequence={'enabled': True, 'keys': [{'camera': wide.id, 'first': 0, 'last': 10},
                                                            {'camera': close.id, 'first': 11, 'last': 20}]})
    result['stored'] = panel._settings_values().get('camera_sequence')


def frames():
    from moonray_modo import host
    scene = modo.Scene()
    fps = float(scene.fps)
    names = {held['wide'].id: 'Wide', held['close'].id: 'Close', scene.renderCamera.id: 'render camera (%s)' % scene.renderCamera.name}
    selection = lx.service.Selection()
    for frame in (5, 15, 30):
        selection.SetTime(frame / fps)
        snapshot = host.snapshot()
        identity = snapshot['camera']['identity']
        result['frames'][frame] = {'camera': names.get(identity, identity), 'size': [snapshot['width'], snapshot['height']],
                                   'keyed': snapshot.get('camera_keyed')}
    selection.SetTime(15 / fps)


def render():
    panel = panel_widget()
    held['runtime'] = panel.preferences.store.value('runtime')
    panel.preferences.set('runtime', str(runtime))
    panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
    panel.start.click()


def rendered():
    panel = panel_widget()
    result['render'] = {'status': panel.status.text(), 'picture': [panel.preview.image.width(), panel.preview.image.height()],
                        'label': panel.image_info.text()}
    from moonray_modo.camera_sequence_dialog import CameraSequence
    dialog = CameraSequence(panel, panel._settings_values().get('camera_sequence'), modo.Scene(), (0, 30), 15)
    dialog.show()
    QtWidgets.QApplication.processEvents()
    result['window_notes'] = dialog.notes.text()
    dialog.grab().save(str(out / 'window.png'))
    dialog.close()
    if held.get('runtime') is None:
        panel.preferences.store.remove('runtime')
    else:
        panel.preferences.store.setValue('runtime', held['runtime'])


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
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    held['wide'] = camera('Wide', -1.0)
    held['close'] = camera('Close', 1.0)
    close = held['close']
    close.channel('resOverride').set(True)
    close.channel('resX').set(640)
    close.channel('resY').set(480)
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, lambda: run([(keys, 500), (frames, 500), (render, 40000), (rendered, 500)]))
