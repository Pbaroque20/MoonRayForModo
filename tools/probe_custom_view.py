# python
"""Bounded CustomView render/display/lifecycle check in an isolated Modo profile."""
import json
import os
import traceback
from pathlib import Path
import lx
import modo
from PySide2 import QtCore, QtWidgets
from moonray_modo.panel import Panel
from moonray_modo import idle

root = Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
folder = root / 'test-results/custom-view'
folder.mkdir(parents=True, exist_ok=True)
report = {'pid': os.getpid(), 'passed': False, 'frames': 0}
panel = None
ticks = 0

def finish(error=None):
    timer.stop()
    if error:
        report['error'] = error
    if panel is not None:
        panel.dispose()
        report['disposed'] = panel.disposed
    (folder / 'report.json').write_text(json.dumps(report, indent=2))
    lx.eval('!app.quit')

def poll():
    global panel, ticks
    ticks += 1
    try:
        if ticks == 1:
            report['version'] = lx.eval('query platformservice appversion ?')
            assert report['version'] == 1619
            lx.eval('moonray.open')
        elif ticks == 3:
            panel = next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel) and w.isVisible())
            panel.settings_toggle.setChecked(False)
            panel.runtime.setText(str(root / 'runtime/native-avx'))
            panel.environment.setValue(1)
            panel.samples.setValue(2)
            panel.size.setCurrentIndex(3)
            panel.renderer.image_ready.connect(frame)
            panel.render_once()
        elif panel is not None and report['frames'] >= 2:
            viewer = panel.preview
            report['valid_gl'] = viewer.isValid()
            # Read our render widget's framebuffer, not the desktop/window.
            image = viewer.grabFramebuffer()
            report['bright_pixels'] = sum(image.pixelColor(x,y).red() > 100
                for y in range(image.height()) for x in range(image.width()))
            assert report['valid_gl'] and report['bright_pixels'] > 100
            viewer.zoom = 2; viewer.pan = QtCore.QPointF(20, 30); viewer.fit()
            assert viewer.zoom == 1 and viewer.pan.isNull()
            report['passed'] = True
            finish()
        elif ticks > 65:
            raise RuntimeError('CustomView render timed out: ' + (panel.status.text() if panel else 'no panel'))
    except Exception:
        finish(traceback.format_exc())

def frame(path):
    report['frames'] += 1

scene = modo.Scene()
scene.renderCamera.position.set((0, 0, 0))
scene.renderCamera.rotation.set((0, 0, 0))
scene.renderItem.channel('resX').set(128)
scene.renderItem.channel('resY').set(128)
mesh = scene.addMesh('CustomView fixture')
geo = mesh.geometry
for point in ((-1,-1,-3),(1,-1,-3),(0,1,-3)):
    geo.vertices.new(point)
geo.polygons.new((0,1,2)); geo.setMeshEdits()

timer = idle.Timer(poll, 2000)
timer.start()
