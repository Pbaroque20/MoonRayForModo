# python
"""Isolated GUI test: overscan follows the camera rendered through.

Modo's render camera is given an overscan of 1.2. Noted, for the scene as it is read and as it is written for a render
to a file (its region window): with no MoonRay camera rendered through, 1.2; with a MoonRay perspective camera of
overscan 1.5 rendered through, 1.5; with that camera's overscan back to none, none, though the render camera still has
1.2."""
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


def read(label):
    from moonray_modo import host, rdla
    snapshot = host.snapshot()
    text = rdla.scene_text(snapshot, 200, 100, 2, 0.0, str(out / 'overscan.exr'))
    windows = [line.strip() for line in text.splitlines() if 'region_window' in line or 'aperture_window' in line]
    through = [e['name'] for e in snapshot.get('entities', []) if e.get('parameters', {}).get('modo_render_camera')]
    result[label] = {'overscan': snapshot['camera'].get('overscan'), 'windows': windows, 'rendered_through': through}


try:
    scene = modo.Scene()
    render_camera = scene.renderCamera
    lx.eval('select.item {%s} set' % render_camera.id)
    lx.eval('item.channel overscan 1.2')
    read('render camera only')
    lx.eval('moonray.entity.add PerspectiveCamera')
    moonray_camera = scene.selected[-1]
    lx.eval('item.channel overscan 1.5')
    lx.eval('item.channel mr_modo_render_camera true')
    read('moonray camera at 1.5')
    lx.eval('select.item {%s} set' % moonray_camera.id)
    lx.eval('item.channel overscan 1.0')
    read('moonray camera at none')
except Exception:
    result['error'] = traceback.format_exc()
(out / 'overscan.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
