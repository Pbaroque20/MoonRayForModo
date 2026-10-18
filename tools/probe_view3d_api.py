# python
"""Isolated GUI test: what Modo's Python can tell of its 3D views, for a camera item to know whether a view looks
through it. Noted: the methods of the 3D view service and of a view, and for each view what they return, with the
viewport looking through a camera placed at (1, 2, 5)."""
import json
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/camera-gate'
out.mkdir(parents=True, exist_ok=True)
result = {}


def plain(value):
    try:
        json.dumps(value)
        return value
    except Exception:
        try:
            return [plain(v) for v in value]
        except Exception:
            return repr(value)


def look():
    service = lx.service.View3Dport()
    result['service_methods'] = [n for n in dir(service) if not n.startswith('_')]
    result['view_methods'] = [n for n in dir(lx.object.View3D) if not n.startswith('_')]
    views = []
    for index in range(service.Count()):
        view = lx.object.View3D(service.View(index))
        found = {}
        for name in result['view_methods']:
            method = getattr(view, name)
            try:
                found[name] = plain(method())
            except Exception as exc:
                found[name] = 'needs args or failed: %s' % str(exc)[:80]
        views.append(found)
    result['views'] = views
    try:
        result['current'] = service.Current()
    except Exception as exc:
        result['current'] = str(exc)


try:
    lx.eval('item.create camera')
    camera = modo.Scene().selected[-1]
    lx.eval('transform.channel pos.X 1.0')
    lx.eval('transform.channel pos.Y 2.0')
    lx.eval('transform.channel pos.Z 5.0')
    lx.eval('view3d.cameraItem {%s}' % camera.id)
    result['camera'] = camera.id
except Exception:
    result['error'] = traceback.format_exc()


def finish():
    try:
        look()
    except Exception:
        result['look_error'] = traceback.format_exc()
    (out / 'view3d_api.json').write_text(json.dumps(result, indent=1, default=str))
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(5000, finish)
