# python
"""Isolated GUI test: a mesh of curves through the preview window, in MoonRay and in MoonLightIPR, and its controls on the mesh's form."""
import json
import math
import pathlib
import random
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/curves-preview'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def windows(name):
    for index, window in enumerate(w for w in QtWidgets.QApplication.topLevelWidgets() if w.isVisible() and w.width() > 300):
        window.grab().save(str(out / ('%s-%d.png' % (name, index))))


try:
    from moonray_modo import options, properties
    scene = modo.Scene()
    ground = scene.addMesh('Ground')
    with ground.geometry as g:
        g.polygons.new([g.vertices.new(place) for place in ((-4, 0, -4), (-4, 0, 4), (4, 0, 4), (4, 0, -4))])
    mesh = scene.addMesh('Strands')
    random.seed(3)
    with mesh.geometry as g:
        polygons = g.internalMesh.PolygonAccessor()

        def polygon(kind, places):
            storage = lx.object.storage('p', len(places))
            storage.set(tuple(g.vertices.new(place).id for place in places))
            polygons.New(kind, storage, len(places), 0)
        for i in range(400):
            a = random.uniform(0, 2 * math.pi)
            r = random.uniform(.05, .8)
            x, z = r * math.cos(a), r * math.sin(a)
            lean = random.uniform(.2, .5)
            polygon(lx.symbol.iPTYP_LINE, [(x * (1 + lean * (j / 7.0) ** 2), 1.2 * j / 7.0, z * (1 + lean * (j / 7.0) ** 2)) for j in range(8)])
        polygon(lx.symbol.iPTYP_CURVE, [(-1.5, .1, 1.2), (-.5, .9, 1.4), (.5, .2, 1.4), (1.5, .9, 1.2)])
    scene.select(mesh)
    values = options.object_values(properties.read(mesh))
    values.update(override=True, curve_root_width=24.0, curve_tip_width=2.0, curve_envelope=1.5)
    properties.write(mesh, options.object_values(values))
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        panel = panel_widget()
        held['engine'] = panel.preview_engine.currentData()
        # The window's choices are shared with the user's own Modo: keep what was stored, to put it back.
        held['runtime'] = panel.preferences.store.value('runtime', '')
        import os
        panel.preferences.set('runtime', str(root / 'runtime' / os.environ.get('PROBE_RUNTIME', 'steady-0349-candidate')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        windows('form')
        panel.start.click()
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(25000, step3)


def step3():
    try:
        panel = panel_widget()
        result['moonray'] = [panel.status.text(), panel.warnings.toPlainText()[:400]]
        panel.window().grab().save(str(out / 'moonray.png'))
        result['engines'] = [panel.preview_engine.itemData(i) for i in range(panel.preview_engine.count())]
        other = next(e for e in result['engines'] if e != 'moonray')
        # MoonLightIPR is in the installed runtime only.
        import os
        panel.preferences.set('runtime', str(pathlib.Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo/runtime'))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(other))
        panel.start.click()
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(20000, step4)


def step4():
    try:
        panel = panel_widget()
        result['moonlightipr'] = [panel.status.text(), panel.warnings.toPlainText()[:400]]
        panel.window().grab().save(str(out / 'moonlightipr.png'))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        if held['runtime']:
            panel.preferences.set('runtime', held['runtime'])
        else:
            panel.preferences.store.remove('runtime')
        result['restored'] = [held['engine'], held['runtime']]
    except Exception:
        result['step4_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(8000, step2)
