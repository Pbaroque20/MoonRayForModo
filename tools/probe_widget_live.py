# python
"""Isolated GUI test: the graph editor's MoonRay Widget with Live material preview on. A material's graph editor is
opened, Live is checked and the widget refreshed: its status should be a picture rendered, not a refusal of the
sampling (Minimum adaptive samples must not exceed maximum samples), with the samples it asked for noted."""
import json
import traceback
from pathlib import Path
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = Path('C:/Users/Raphael Tobar/MoonRayForModo/test-results/widget-live')
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def editor():
    from moonray_modo.node_editor import Editor
    return next(w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, Editor) and w.isVisible())


def live_on():
    try:
        panel = editor().material_preview
        held['panel'] = panel
        original = panel.renderer.submit

        def submit(scene, runtime, width, height, *args, **kw):
            s = scene['render_settings']
            result['submitted'] = {'min': s['min_adaptive_samples'], 'max': s['max_adaptive_samples'], 'size': (width, height)}
            return original(scene, runtime, width, height, *args, **kw)
        panel.renderer.submit = submit
        panel.live.setVisible(True)
        panel.live.setChecked(True)
        panel.refresh()
        result['status_at_refresh'] = panel.status.text()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(20000, look)


def look():
    try:
        panel = held['panel']
        result['status_after'] = panel.status.text()
        result['live'] = panel.live.isChecked()
        editor().grab().save(str(out / 'live.png'))
        panel.live.setChecked(False)
        editor().close()
    except Exception:
        result['error2'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


try:
    from moonray_modo import native, nodes, properties
    native.default_runtime = lambda: 'C:/Users/Raphael Tobar/AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
    item = modo.Scene().addMaterial(name='WidgetLive')
    properties.write(item, {'node_graph': nodes.new(), 'node_override': True})
    modo.Scene().select(item)
    lx.eval('moonray.material.nodes')
    QtCore.QTimer.singleShot(8000, live_on)
except Exception:
    result['error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')
