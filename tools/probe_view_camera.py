# python
"""GUI: what a 3D viewport looking through the render camera says of itself (lx.service.View3Dport), beside the
camera's own world matrix, to follow a camera navigated in a viewport before Modo moves the camera item (on release).
Writes test-results/view-camera.json."""
import json, pathlib, traceback, lx, lxu, modo
from PySide2 import QtCore
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\view-camera.json')
result = {}


def matrix(m):
    try:
        return [list(row) for row in lx.object.Matrix(m).Get4()]
    except Exception as exc:
        return 'matrix? %s' % exc


def look():
    try:
        scene = modo.Scene()
        camera = scene.renderCamera
        from moonray_modo.host import world_matrix
        result['camera'] = world_matrix(camera)
        ports = lx.service.View3Dport()
        result['count'] = ports.Count()
        result['current'] = ports.Current()
        views = []
        for index in range(ports.Count()):
            view = lx.object.View3D(ports.View(index))
            entry = {}
            for name in ('Space', 'Axis', 'Center', 'Angles', 'Scale', 'Dimensions', 'Distance', 'Bounds'):
                try:
                    entry[name] = repr(getattr(view, name)())
                except Exception as exc:
                    entry[name] = 'x %s' % exc
            for flag in (0, 1):
                try:
                    entry['Matrix%d' % flag] = repr(view.Matrix(flag))
                except Exception as exc:
                    entry['Matrix%d' % flag] = 'x %s' % exc
            try:
                entry['EyeVector'] = repr(view.EyeVector((0.0, 0.0)))
            except Exception as exc:
                entry['EyeVector'] = 'x %s' % exc
            entry['methods'] = [m for m in dir(view) if not m.startswith('_')]
            views.append(entry)
        result['views'] = views
    except Exception:
        result['error'] = traceback.format_exc()
    out.write_text(json.dumps(result, indent=1, default=str))
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


try:
    lx.eval('scene.open {%s} normal' % r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\bump-node\bump_node.lxo')
    try:
        lx.eval('view3d.projection cam')
    except Exception as exc:
        result['projection'] = str(exc)
except Exception:
    result['open_error'] = traceback.format_exc()
QtCore.QTimer.singleShot(6000, look)
