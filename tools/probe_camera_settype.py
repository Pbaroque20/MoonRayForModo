# python
"""Isolated GUI test: Convert to MoonRay Camera replaces the Modo camera.

A camera, Shot, is keyed at frames 0 and 10 (moving along X), parented to a locator, given a child locator, made the
render camera and named in a Camera Sequence key. After moonray.camera.convert (perspective), noted: whether Shot is
still a Modo camera, the MoonRay camera's identity, type and name, its parent and children, its position at frames 0
and 10, the render camera, the key's camera, and the focal length it took (Modo's 50 mm)."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/viewport-cameras'
out.mkdir(parents=True, exist_ok=True)
result = {}


def state(item_id):
    scene = modo.Scene()
    try:
        item = scene.item(item_id)
    except LookupError:
        return {'found': False}
    locator = modo.LocatorSuperType(item)
    fps = float(scene.fps)
    return {'found': True, 'id': item.id, 'type': item.type, 'name': item.name, 'parent': item.parent.name if item.parent else None,
            'children': [c.name for c in item.children()], 'x_at_10': locator.position.x.get(10 / fps), 'x_at_0': locator.position.x.get(0.0),
            'render_camera': scene.renderCamera.id if scene.renderCamera else None}


try:
    scene = modo.Scene()
    fps = float(scene.fps)
    lx.eval('item.create locator')
    holder = scene.selected[-1]
    holder.name = 'Rig'
    lx.eval('item.create camera')
    shot = scene.selected[-1]
    shot.name = 'Shot'
    lx.eval('item.parent {%s} {%s} 0 inPlace:1' % (shot.id, holder.id))
    lx.eval('item.create locator')
    child = scene.selected[-1]
    child.name = 'Marker'
    lx.eval('item.parent {%s} {%s} 0 inPlace:1' % (child.id, shot.id))
    lx.eval('select.item {%s} set' % shot.id)
    lx.eval('render.camera {%s}' % shot.id)
    for frame, x in ((0, 0.0), (10, 3.0)):
        modo.LocatorSuperType(shot).position.x.set(x, time=frame / fps, key=True)
    from moonray_modo import properties
    stored = properties.scene_settings()
    stored['camera_sequence'] = {'enabled': True, 'keys': [{'camera': shot.id, 'first': 0, 'last': 20}]}
    properties.write(scene.renderItem, stored)
    result['before'] = state(shot.id)
    lx.eval('select.item {%s} set' % shot.id)
    try:
        lx.eval('moonray.camera.convert 0')
        result['convert'] = 'ok'
    except Exception as exc:
        result['convert'] = 'error: %s' % exc
    now = modo.Scene().selected
    result['selected_after'] = [(i.id, i.type, i.name) for i in now]
    after_id = now[-1].id if now else shot.id
    result['after'] = state(after_id)
    result['modo_cameras_left'] = [i.name for i in modo.Scene().items('camera', superType=False)]
    result['key_camera'] = (properties.scene_settings().get('camera_sequence') or {}).get('keys')
    try:
        result['mr_focal'] = modo.Scene().item(after_id).channel('mr_focal').get()
    except Exception as exc:
        result['mr_focal'] = 'error: %s' % exc
except Exception:
    result['error'] = traceback.format_exc()
(out / 'settype.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
