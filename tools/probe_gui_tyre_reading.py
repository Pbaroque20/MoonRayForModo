# python
"""GUI: what MoonLightIPR's realtime is handed of a scene's instanced meshes (a car's tyres), as Modo's preview window
sends it: PROBE_SCENE opened (the Lamborghini unless named), MoonLightIPR's realtime switched on, and once its picture is
in and PROBE_SETTLE seconds (20) have passed, each instanced mesh of the scene last sent (the panel's _kept_capture)
summed up: its points' extent, its faces, each placement's scale and place, at the shutter's close too; and each mesh
packed for MoonLightIPR (mesh_payload): its extent and faces as packed, and how it was made lighter, for the instanced
ones and the 12 heaviest. Writes test-results/tyre-reading/<engine>.json and the picture; RT off and Modo quits."""
import json
import math
import os
import pathlib
import time
import traceback
import lx
from PySide2 import QtCore, QtWidgets

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\tyre-reading'))
out.mkdir(parents=True, exist_ok=True)
engine = os.environ.get('PROBE_ENGINE', 'moonlightipr')
scene_path = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\Lamborghini(1)\Lamborghini_Moonray.lxo')
settle = float(os.environ.get('PROBE_SETTLE', '20'))
result = {'scene': scene_path, 'engine': engine, 'packed': []}
held = {'began': time.monotonic()}


def save():
    (out / ('%s.json' % engine)).write_text(json.dumps(result, indent=1, default=str))


def scale(m):
    if not m or len(m) != 16:
        return None
    return [round(math.sqrt(sum(m[r * 4 + c] ** 2 for c in range(3))), 4) for r in range(3)]


def extent(points):
    if not points:
        return None
    try:
        return [[round(min(p[a] for p in points), 4), round(max(p[a] for p in points), 4)] for a in range(3)]
    except Exception:
        return 'unreadable: %s' % type(points).__name__


def later(ms, step):
    def run():
        try:
            step()
        except Exception:
            result.setdefault('errors', []).append(step.__name__ + ': ' + traceback.format_exc())
            finish()
    QtCore.QTimer.singleShot(ms, run)


def panel():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def picture_key():
    image = panel().preview.image
    return None if image.isNull() else image.cacheKey()


try:
    from moonray_modo import moonlightipr_scene
    original_payload = moonlightipr_scene.mesh_payload

    def recorded(mesh, material_index, slots, simplified=None):
        value = original_payload(mesh, material_index, slots, simplified)
        try:
            faces = len(mesh.get('faces') or [])
            result['packed'].append({'identity': mesh.get('identity'), 'faces': faces, 'instanced': 'instances' in mesh,
                                     'simplified': simplified, 'extent': extent(mesh.get('vertices')) if 'instances' in mesh or faces > 200000 else None,
                                     'baked_instance_scale': mesh.get('baked_instance_scale')})
        except Exception:
            result.setdefault('record_errors', []).append(traceback.format_exc()[-300:])
        return value
    moonlightipr_scene.mesh_payload = recorded
except Exception:
    result['hook_error'] = traceback.format_exc()


def switch_on():
    p = panel()
    p.preview_engine.setCurrentIndex(p.preview_engine.findData(engine))
    held['picture'] = picture_key()
    held['rt'] = time.monotonic()
    p.rt.click()
    result['rt_checked'] = p.rt.isChecked()
    later(500, wait_picture)


def wait_picture():
    if picture_key() in (None, held['picture']) and time.monotonic() - held['rt'] < 900:
        later(500, wait_picture)
        return
    result['first_picture_seconds'] = round(time.monotonic() - held['rt'], 2)
    later(int(settle * 1000), summarize)


def summarize():
    p = panel()
    scene = getattr(p, '_kept_capture', None)
    result['status'] = p.status.text()
    try:
        from moonray_modo import geometry_cache
        result['geometry_cache'] = dict(geometry_cache.LAST)
    except Exception:
        pass
    if scene is None:
        result['kept'] = None
    else:
        meshes = scene.get('meshes') or []
        result['meshes'] = len(meshes)
        result['detail'] = scene.get('_geometry_detail')
        result['motion_steps'] = scene.get('motion_steps')
        result['instanced'] = []
        for mesh in meshes:
            if 'instances' not in mesh:
                continue
            result['instanced'].append({
                'identity': mesh.get('identity'), 'faces': len(mesh.get('faces') or []), 'points': len(mesh.get('vertices') or []),
                'extent': extent(mesh.get('vertices')), 'matrix_scale': scale(mesh.get('matrix')),
                'instances': [[scale(m), [round(v, 3) for v in m[12:15]]] for m in mesh['instances']],
                'instances_close': [[scale(m), [round(v, 3) for v in m[12:15]]] for m in (mesh.get('instances_close') or [])],
                'instance_ids': mesh.get('instance_ids'), 'baked_instance_scale': mesh.get('baked_instance_scale'),
                'vertices_close': bool(mesh.get('vertices_close'))})
    result['packed'] = sorted(result['packed'], key=lambda entry: (not entry['instanced'], -entry['faces']))[:16]
    p.preview.image.save(str(out / ('%s.png' % engine)))
    save()
    if p.rt.isChecked():
        p.rt.click()
    later(3000, finish)


def finish():
    result['done'] = True
    save()
    QtCore.QTimer.singleShot(3000, lambda: lx.eval('!app.quit'))


try:
    lx.eval('!scene.open {%s} normal' % scene_path)
    result['opened_at'] = round(time.monotonic() - held['began'], 2)
    lx.eval('moonray.page preview')
    later(8000, switch_on)
except Exception:
    result['errors'] = [traceback.format_exc()]
    finish()
save()
