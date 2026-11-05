# python
"""GUI: a Modo Mesh Light in XPU2 and MoonLightIPR. A floor and a hidden panel above it, the panel the Prototype of a
Mesh Light (radiance 3), Modo's own lights and environment off; rendered in the preview window by XPU2 (MoonRay engine,
XPU2 chosen) and by MoonLightIPR, the window grabbed after each. Writes test-results/mesh-light-engines/."""
import json
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\mesh-light-engines')
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def settings():
    from moonray_modo import native
    return QtCore.QSettings('MoonRayForModo', native.settings_name())


def quad(scene, name, size, up):
    mesh = scene.addMesh(name)
    with mesh.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-size, 0, -size), (size, 0, -size), (size, 0, size), (-size, 0, size))]
        geo.polygons.new(list(reversed(points)) if up else points)
    return mesh


try:
    s = settings()
    held['xpu2/renderer'] = s.value('xpu2/renderer')
    s.setValue('xpu2/renderer', 'xpu2'); s.sync()
    scene = modo.Scene()
    quad(scene, 'Floor', 3.0, True)
    panel = quad(scene, 'Panel', 0.5, False)
    panel.position.set((0.0, 2.0, 0.0))
    panel.channel('visible').set('off')
    lx.eval('item.create meshLight')
    light = next(i for i in scene.items('meshLight', superType=False))
    lx.eval('select.item {%s} set' % light.id)
    lx.eval('light.mesh mesh:{%s}' % panel.id)
    light.channel('radiance').set(3.0)
    for other in [i for i in scene.items('light') if i.type != 'meshLight']:
        other.channel('render').set('off')
    for environment in list(scene.items('environment')):
        result.setdefault('environment', []).append(environment.name)
        scene.removeItems(environment)
    camera = scene.renderCamera or modo.Camera(next(iter(scene.items('camera'))))
    camera.position.set((0.0, 3.5, 6.0))
    camera.rotation.set((-0.5, 0.0, 0.0))
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def render(label, engine, then):
    try:
        p = panel_widget()
        p.preview_engine.setCurrentIndex(p.preview_engine.findData(engine))
        p.render_once()
        began = time.monotonic()

        def wait():
            try:
                q = panel_widget()
                if (getattr(q, '_rendering', False) and time.monotonic() - began < 180) or time.monotonic() - began < 6:
                    QtCore.QTimer.singleShot(1500, wait); return

                def grab():
                    QtWidgets.QApplication.processEvents()
                    q.window().grab().save(str(out / (label + '.png')))
                    result['steps'].append([label, q.status.text(), q.image_info.text(), q.render_timing.text()])
                    try:
                        from moonray_modo import preview_diagnostics
                    except Exception:
                        pass
                    save(); then()
                QtCore.QTimer.singleShot(5000, grab)
            except Exception:
                result[label + '_wait_error'] = traceback.format_exc(); save(); finish()
        QtCore.QTimer.singleShot(2000, wait)
    except Exception:
        result[label + '_error'] = traceback.format_exc(); save(); finish()


def finish():
    try:
        s = settings()
        for key, value in held.items():
            if value is None: s.remove(key)
            else: s.setValue(key, value)
        s.sync()
        panel_widget().stop()
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('app.quit'))


QtCore.QTimer.singleShot(6000, lambda: render('xpu2', 'moonray', lambda: render('moonlightipr', 'moonlightipr', finish)))
