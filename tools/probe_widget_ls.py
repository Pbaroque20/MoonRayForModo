# python
"""Isolated GUI test: the graph editor's MoonRay Widget, under MoonRay LS, started as the editor opens and kept.

The graph editor is opened on a material; with nothing clicked, the time to the widget's first picture and to its
finished one are written down, with the scene's sampling and what the one Refresh/Stop button reads, and the widget pictured. The editor is closed and opened
again: the picture should be there at once, from the cache, with no render."""
import json
import time
import traceback
from pathlib import Path
import lx
import modo
from PySide2 import QtCore, QtWidgets

ROOT = Path('C:/Users/Raphael Tobar/MoonRayForModo')
out = ROOT / 'test-results/widget-ls'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def editor():
    from moonray_modo.node_editor import Editor
    return next(w for w in QtWidgets.QApplication.topLevelWidgets() if isinstance(w, Editor) and w.isVisible())


def watch(name):
    """Times from the editor opening to the widget's first picture and its finished one."""
    e = editor()
    panel = e.material_preview
    held['panel'] = panel
    events = result.setdefault(name, {})
    start = held['opened']
    panel.renderer.image_object.connect(lambda *_: events.setdefault('first_picture_s', round(time.time() - start, 2)))
    panel.renderer.image_object.connect(lambda *_: events.setdefault('button_while_rendering', panel.button.text()))
    panel.renderer.image_ready.connect(lambda *_: events.setdefault('first_picture_s', round(time.time() - start, 2)))
    panel.renderer.finished.connect(lambda *_: events.setdefault('finished_s', round(time.time() - start, 2)))
    original = panel.renderer.submit

    def submit(scene, runtime, width, height, *args, **kw):
        s = scene['render_settings']
        events['submitted'] = {'size': (width, height), 'ls': scene.get('_ipr'), 'sampling_mode': s['sampling_mode'],
                               'max_samples': s['max_adaptive_samples'], 'error': s['target_adaptive_error'],
                               'light_samples': s['light_samples']}
        return original(scene, runtime, width, height, *args, **kw)
    panel.renderer.submit = submit


def first():
    try:
        watch('first_open')
        QtCore.QTimer.singleShot(20000, shot1)
    except Exception:
        result['error'] = traceback.format_exc(); save(); lx.eval('!app.quit')


def shot1():
    try:
        from moonray_modo import material_preview
        panel = held['panel']
        result['first_open']['status'] = panel.status.text()
        result['first_open']['cached_pictures'] = len(material_preview.CACHE)
        result['first_open']['button_after'] = panel.button.text()
        editor().grab().save(str(out / '1_first_open.png'))
        editor().close()
    except Exception:
        result['error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(1500, reopen)


def reopen():
    try:
        held['opened'] = time.time()
        lx.eval('moonray.material.nodes')
        QtCore.QTimer.singleShot(100, lambda: watch('reopened'))
        QtCore.QTimer.singleShot(1500, shot2)
    except Exception:
        result['error2'] = traceback.format_exc(); save(); lx.eval('!app.quit')


def shot2():
    try:
        panel = held['panel']
        result['reopened']['status'] = panel.status.text()
        result['reopened']['image_shown'] = not getattr(panel.viewer, 'image', None) is None if hasattr(panel.viewer, 'image') else None
        editor().grab().save(str(out / '2_reopened.png'))
        editor().close()
    except Exception:
        result['error2'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


try:
    from moonray_modo import native, nodes, properties
    native.default_runtime = lambda: 'C:/Users/Raphael Tobar/AppData/Roaming/Luxology/Kits/MoonRayForModo/runtime'
    item = modo.Scene().addMaterial(name='WidgetLS')
    properties.write(item, {'node_graph': nodes.new(), 'node_override': True})
    modo.Scene().select(item)
    held['opened'] = time.time()
    lx.eval('moonray.material.nodes')
    QtCore.QTimer.singleShot(50, first)
except Exception:
    result['error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')
