# python
"""Isolated GUI test helper: keep a scene (MOONRAY_PROBE_SCENE) as the plugin reads it, for work on what is made of a
snapshot outside Modo (tools/time_scene_text.py). Written to test-results/snapshot/scene.pickle."""
import os
import pathlib
import pickle
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/snapshot'
out.mkdir(parents=True, exist_ok=True)


def dump():
    try:
        from moonray_modo.panel import Panel
        panel = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray_ls'))
        scene = panel._capture_preview()
        values = panel._settings_values()
        with open(str(out / 'scene.pickle'), 'wb') as stream:
            pickle.dump({'scene': scene, 'samples': values['samples'], 'environment': values['environment']}, stream, protocol=2)
        (out / 'done.txt').write_text('%d meshes' % len(scene.get('meshes', [])))
    except Exception:
        (out / 'done.txt').write_text(traceback.format_exc())
    lx.eval('!app.quit')


try:
    if os.environ.get('MOONRAY_PROBE_SCENE'):
        lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    lx.eval('moonray.open')
except Exception:
    (out / 'done.txt').write_text(traceback.format_exc())
QtCore.QTimer.singleShot(8000, dump)
