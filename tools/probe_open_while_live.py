# python
"""Isolated GUI test: a scene opened while the preview is already following in realtime.

The preview window is opened on an empty scene with MoonLightIPR chosen, which switches realtime on. A scene
(MOONRAY_PROBE_SCENE) is then opened. What the window says afterwards, and what the engine printed, are written down."""
import json
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/open-while-live'
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {}
SCENE = os.environ.get('MOONRAY_PROBE_SCENE', '')
ENGINE = os.environ.get('MOONRAY_PROBE_ENGINE', 'moonlightipr')


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def note(name):
    panel = panel_widget()
    scene = getattr(panel, '_ipr_refine_scene', None) or {}
    result['steps'].append({'step': name, 'status': panel.status.text(), 'tooltip': panel.status.toolTip()[:300], 'button': panel.start.text(), 'following': panel._following,
                            'rendering': panel._rendering, 'picture': not panel.preview.image.isNull(), 'meshes': len(scene.get('meshes', [])),
                            'log': [line[:200] for line in str(panel.renderer.log).splitlines() if line.strip() and not line.startswith('@@MODO_SHARED')][-6:]})
    panel.window().grab().save(str(out / (name + '.png')))
    save()


def begin():
    try:
        panel = panel_widget()
        held['stored'] = [panel.preferences.store.value(key, None) for key in ('runtime', 'preview_engine', 'ipr')]
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-0350-pool')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(ENGINE))
    except Exception:
        result['error'] = traceback.format_exc()
    QtCore.QTimer.singleShot(6000, load)


def load():
    note('live_on_empty_scene')
    try:
        lx.eval('!scene.open {%s} normal' % SCENE)
        result['opened'] = True
    except Exception:
        result['open_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(int(os.environ.get('MOONRAY_PROBE_WAIT', '45')) * 1000, finish)


def finish():
    try:
        note('after_scene_opened')
        panel = panel_widget()
        if panel._rendering or panel._following:
            panel.stop()
        for key, value in zip(('runtime', 'preview_engine', 'ipr'), held['stored']):
            if value is None:
                panel.preferences.store.remove(key)
            else:
                panel.preferences.store.setValue(key, value)
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


try:
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
