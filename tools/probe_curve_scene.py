# python
"""Isolated GUI test: a scene with a curve in it renders.

A ball, and beside it a mesh holding one curve of five points (MOONRAY_PROBE_CURVE: curve, bezier or bspline; also
'own' for the curve in a mesh item of its own, the default, or 'same' in the ball's mesh). The scene is read as a
render reads it and rendered with the engine in MOONRAY_PROBE_ENGINE; what reading it says, the status and any error
are written down, and the window pictured."""
import json
import os
import pathlib
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
ENGINE = os.environ.get('MOONRAY_PROBE_ENGINE', 'moonray')
KIND = os.environ.get('MOONRAY_PROBE_CURVE', 'curve')
WHERE = os.environ.get('MOONRAY_PROBE_WHERE', 'own')
tag = '%s-%s-%s' % (ENGINE, KIND, WHERE)
out = root / 'test-results/curve-scene'
out.mkdir(parents=True, exist_ok=True)
result = {'engine': ENGINE, 'curve': KIND, 'where': WHERE}


def save():
    (out / (tag + '.json')).write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def begin():
    try:
        from moonray_modo import host
        try:
            scene = host.snapshot(refresh_materials=True)
            result['snapshot'] = {'warnings': scene['warnings'], 'meshes': [[m.get('name'), len(m.get('faces') or [])] for m in scene['meshes']],
                                  'extra': [[e.get('name'), e.get('kind'), len(e.get('counts') or [])] for e in scene.get('extra_geometry') or []]}
        except Exception:
            result['snapshot'] = {'error': traceback.format_exc()}
        save()
        panel = panel_widget()
        panel.preferences.set('runtime', str(root / os.environ.get('MOONRAY_PROBE_RUNTIME', 'runtime/steady-04-drain')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(ENGINE))
        panel.start.click()
    except Exception:
        result['error'] = traceback.format_exc()
        save()
        lx.eval('!app.quit')
        return
    QtCore.QTimer.singleShot(28000 if ENGINE == 'moonray' else 9000, finish)


def finish():
    panel = panel_widget()
    result['status'] = panel.status.text()
    result['picture'] = not panel.preview.image.isNull()
    result['rendering'] = panel._rendering
    log = str(getattr(panel.renderer, 'log', '') or '')
    result['log'] = sorted({line.strip()[:260] for line in log.splitlines() if any(word in line.lower() for word in ('warn', 'error', 'fail', 'fatal'))})[:20]
    result['notices'] = (panel.renderer.active or {}).get('snapshot', {}).get('warnings')
    panel.window().grab().save(str(out / (tag + '.png')))
    save()
    panel.stop()
    QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))


try:
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    ball = modo.Scene().selected[0]
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    if WHERE == 'own':
        lx.eval('item.create mesh')
    holder = modo.Scene().selected[0]
    points = [(-1.5, 0.0, 0.0), (-1.2, 0.5, 0.2), (-0.9, 0.9, 0.0), (-0.6, 1.2, -0.2), (-0.3, 1.4, 0.0)]
    with holder.geometry as geometry:
        made = [geometry.vertices.new(point) for point in points]
        for vertex in made:
            vertex.select()
    lx.eval('select.typeFrom vertex')
    lx.eval('select.drop vertex')
    for vertex in made:
        lx.eval('select.element %d vertex add %d' % (lx.eval('query layerservice layer.index ? main'), vertex.index))
    lx.eval('poly.make %s' % KIND)
    lx.eval('select.typeFrom item')
    kinds = {}
    for polygon in holder.geometry.polygons:
        import lxu.utils
        name = lxu.utils.decodeID4(polygon.accessor.Type())
        kinds[name] = kinds.get(name, 0) + 1
    result['polygons'] = kinds
    lx.eval('moonray.render.samples 2')
    lx.eval('moonray.open')
except Exception:
    result['setup_error'] = traceback.format_exc()
save()
QtCore.QTimer.singleShot(8000, begin)
