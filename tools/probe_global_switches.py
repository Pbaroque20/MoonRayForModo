# python
"""Isolated GUI test: the Render item's Global Switches, and the dicing camera popup.

A second Modo camera and a MoonRay camera item are added. The dicing camera popup's entries are written down; the
second camera is chosen through the popup's command, and the scene is read as for a render to see that it carries that
camera. Shadows are switched off through their command and read back. The Render item is selected and Modo's window
pictured, with the Global Switches section."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/global-switches-gui'
out.mkdir(parents=True, exist_ok=True)
result = {}


def finish():
    try:
        shown = [w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible()]
        max(shown, key=lambda w: w.width() * w.height()).grab().save(str(out / 'render_item.png'))
    except Exception:
        result['shot_error'] = traceback.format_exc()
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
    QtCore.QTimer.singleShot(500, lambda: lx.eval('app.quit'))


try:
    scene = modo.Scene()
    second = scene.addItem('camera', name='Overview')
    second.position.set((0.0, 3.0, 12.0))
    lx.eval('moonray.entity.add PerspectiveCamera')
    from moonray_modo import camera_choice, host, properties, rdla
    entries = camera_choice.dicing_choices()
    result['popup'] = [label for label, _ in entries]
    index = next(i for i, (label, _) in enumerate(entries) if label.endswith('Overview'))
    lx.eval('moonray.dicing_camera %d' % index)
    result['stored'] = properties.scene_settings().get('dicing_camera') == second.id
    result['queried'] = lx.eval('moonray.dicing_camera ?')
    lx.eval('moonray.render.enable_shadowing 0')
    result['shadows_stored'] = properties.scene_settings().get('render', {}).get('enable_shadowing')
    snapshot = host.snapshot()
    result['snapshot_dicing'] = {k: v for k, v in (snapshot.get('dicing_camera') or {}).items() if k != 'matrix'}
    snapshot['render_settings'] = properties.scene_settings().get('render', {})
    text = rdla.scene_text(snapshot)
    result['scene'] = [line.strip() for line in text.splitlines() if 'dicing' in line or 'enable_shadowing' in line or 'lights_visible' in line]
    lx.eval('select.item {%s} set' % scene.renderItem.id)
except Exception:
    result['error'] = traceback.format_exc()
QtCore.QTimer.singleShot(5000, finish)
