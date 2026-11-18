# python
"""A test Modo left open for the user: the Hyundai scene, the MoonRay window, MoonLightIPR as the preview engine."""
import os
import pathlib
import traceback
import lx
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
log = root / 'test-results/open-for-testing.txt'


def ready():
    try:
        from moonray_modo.panel import Panel
        panel = next(w for w in QtWidgets.QApplication.topLevelWidgets() + QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))
        panel.preferences.set('runtime', str(root / 'dist/personal-kit/Luxology/Kits/MoonRayForModo/runtime'))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
        log.write_text('ready\n')
    except Exception:
        log.write_text(traceback.format_exc())


try:
    lx.eval('scene.open {%s} normal' % os.environ.get('MOONRAY_TEST_SCENE', r'C:/Users/Raphael Tobar/Downloads/Hyundai N Vision 74/Hyundai N Vision 74_Studio_MoonRay.lxo'))
    lx.eval('moonray.open')
except Exception:
    log.write_text(traceback.format_exc())
QtCore.QTimer.singleShot(4000, ready)
