# python
"""Isolated GUI test: bring an OpenVDB file in as a MoonRay VDB shape and render it in the preview window.

The file is PROBE_VDB, or the first .vdb in PROBE_VDB_FOLDER."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/vdb'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


try:
    from moonray_modo import entities, host, rdla
    source = os.environ.get('PROBE_VDB', '')
    scene = modo.Scene()
    item = scene.addItem(entities.item_type('VdbGeometry'), name='Cloud')
    scene.select(item)
    lx.eval('moonray.entity.loadVdb {%s}' % source)
    prefix = entities.CHANNEL_PREFIX
    result['after_load'] = {key: item.channel(prefix + key).get() for key in ('model', 'density_grid', 'emission_grid', 'velocity_grid', 'modo_volume')}
    result['items'] = sorted(i.name for i in scene.items() if i.type.startswith('moonray.'))
    names = entities.classes()
    i = names.index('VdbGeometry')
    for j, (key, channel, plan, default, choices) in enumerate(entities.channels('VdbGeometry')):
        if key in ('density_grid', 'model', 'modo_volume'):
            kind = 'pick' if key == 'modo_volume' else 'option'
            result.setdefault('queries', {})[key] = lx.eval('moonray.entity.%s%d_%d ?' % (kind, i, j))
    camera = scene.renderCamera
    size = float(os.environ.get('PROBE_VDB_DISTANCE', '6'))
    camera.position.set((size * .6, size * .35, size))
    camera.rotation.set((-17.0, 31.0, 0.0), degrees=True)
    snapshot = host.snapshot()
    result['warnings'] = snapshot.get('warnings')
    result['entities'] = [{k: v for k, v in e.items() if k != 'matrix'} for e in snapshot.get('entities', [])]
    (out / 'modo_scene.rdla').write_text(rdla.scene_text(snapshot, 480, 270, 3, .3, str(out / 'modo_scene.exr')), encoding='utf-8')
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        panel = panel_widget()
        held['engine'] = panel.preview_engine.currentData()
        held['ipr'] = panel.preferences.store.value('ipr', '')
        held['runtime'] = panel.preferences.store.value('runtime', '')
        panel.preferences.set('runtime', str(root / 'runtime' / os.environ.get('PROBE_RUNTIME', 'steady-0349-candidate')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        panel.start.click()
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(30000, step3)


def step3():
    try:
        panel = panel_widget()
        result['preview'] = [panel.status.text(), panel.warnings.toPlainText()[:500]]
        panel.window().grab().save(str(out / 'preview.png'))
        if panel._rendering:
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        # The window's choices are shared with the user's own Modo: put back what was stored.
        for key in ('runtime', 'ipr'):
            if held[key]:
                panel.preferences.store.setValue(key, held[key])
            else:
                panel.preferences.store.remove(key)
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(8000, step2)
