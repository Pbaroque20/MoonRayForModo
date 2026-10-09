# python
"""Isolated GUI test: hair grown from guide curves on a scalp mesh, both ways of growing, through the object override's own commands,
and rendered in the preview window by MoonRay and by MoonLightIPR."""
import json
import math
import os
import pathlib
import random
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/hair'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}
RADIUS = 0.5


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


def collected():
    from moonray_modo import extra_geometry, properties
    warnings = []
    started = time.time()
    entries = extra_geometry.collect(modo.Scene(), warnings, properties.scene_settings().get('production', {}))
    return entries, warnings, round(time.time() - started, 2)


try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    for name, value in (('cenX', 0), ('cenY', RADIUS), ('cenZ', 0), ('sizeX', RADIUS), ('sizeY', RADIUS), ('sizeZ', RADIUS)):
        lx.eval('tool.attr prim.sphere %s %s' % (name, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    scene = modo.Scene()
    scalp = scene.selected[0]
    scalp.name = 'Scalp'
    guides = scene.addMesh('Guides')
    random.seed(5)
    with guides.geometry as g:
        polygons = g.internalMesh.PolygonAccessor()
        for i in range(60):
            a, b = random.uniform(.1, 1.2), random.uniform(0, 2 * math.pi)
            normal = (math.sin(a) * math.cos(b), math.cos(a), math.sin(a) * math.sin(b))
            places = []
            for j in range(7):
                reach = RADIUS + .35 * j / 6.0
                # Out from the scalp, then drooping.
                places.append((normal[0] * reach, RADIUS + normal[1] * reach - .12 * (j / 6.0) ** 2, normal[2] * reach))
            storage = lx.object.storage('p', len(places))
            storage.set(tuple(g.vertices.new(place).id for place in places))
            polygons.New(lx.symbol.iPTYP_LINE, storage, len(places), 0)
    scene.select(guides)
    lx.eval('moonray.object.override 1')
    lx.eval('moonray.object.curve_root_width 3.0')
    lx.eval('moonray.object.curve_tip_width 0.5')
    plain = collected()
    result['guides_only'] = [[len(e['counts']) for e in plain[0]], plain[1]]
    lx.eval('moonray.object.hair 1')
    unplaced = collected()
    result['no_scalp'] = [[len(e['counts']) for e in unplaced[0]], unplaced[1]]
    # The scalp is chosen from the popup: none, then the scene's other meshes by name.
    from lxserv import moonray_commands
    choices = moonray_commands.scalp_choices()
    result['scalp_choices'] = [label for _, label in choices]
    lx.eval('moonray.object.hair_scalp %d' % next(i for i, (_, label) in enumerate(choices) if label == 'Scalp'))
    lx.eval('moonray.object.hair_count 60')
    lx.eval('moonray.object.hair_width 60.0')
    lx.eval('moonray.object.hair_clump 0.7')
    result['queries'] = {key: lx.eval('moonray.object.%s ?' % key) for key in ('hair', 'hair_scalp', 'hair_mode', 'hair_count', 'hair_width', 'hair_clump', 'hair_seed')}
    for mode, name in ((0, 'clusters'), (1, 'between')):
        lx.eval('moonray.object.hair_mode %d' % mode)
        entries, warnings, seconds = collected()
        again = collected()
        strands = entries[0]
        roots, start = [], 0
        for count in strands['counts']:
            p = strands['vertices'][start]
            roots.append(math.sqrt(p[0] ** 2 + (p[1] - RADIUS) ** 2 + p[2] ** 2))
            start += count
        result[name] = {'strands': len(strands['counts']), 'points': len(strands['vertices']), 'seconds': seconds, 'seconds_again': again[2],
                        'root_distance_from_centre': [round(min(roots), 4), round(max(roots), 4)], 'warnings': warnings}
    # A guide drawn away from the scalp cannot be put on it, and says so.
    lx.eval('moonray.object.hair_mode 0')
    lx.eval('moonray.object.hair_width 5.0')
    with guides.geometry as g:
        polygons = g.internalMesh.PolygonAccessor()
        places = [(3.0, 1.0 + .1 * j, 0.0) for j in range(4)]
        storage = lx.object.storage('p', len(places))
        storage.set(tuple(g.vertices.new(place).id for place in places))
        polygons.New(lx.symbol.iPTYP_LINE, storage, len(places), 0)
    result['adrift'] = collected()[1]
    lx.eval('moonray.object.hair_width 60.0')
    camera = scene.renderCamera
    camera.position.set((1.3, 1.1, 2.3))
    camera.rotation.set((-13.0, 29.5, 0.0), degrees=True)
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def step2():
    try:
        panel = panel_widget()
        held['engine'] = panel.preview_engine.currentData()
        held['ipr'] = panel.preferences.store.value('ipr', '')
        held['runtime'] = panel.preferences.store.value('runtime', '')
        panel.preferences.set('runtime', str(root / 'runtime' / os.environ.get('PROBE_RUNTIME', 'steady-0349-candidate')))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonray'))
        QtWidgets.QApplication.processEvents()
        if panel.start.text() == 'Render':
            panel.start.click()
    except Exception:
        result['step2_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(45000, step3)


def step3():
    try:
        panel = panel_widget()
        result['moonray'] = [panel.status.text(), panel.warnings.toPlainText()[:500]]
        panel.window().grab().save(str(out / 'moonray_clusters.png'))
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preferences.set('runtime', str(pathlib.Path(os.environ['APPDATA']) / 'Luxology/Kits/MoonRayForModo/runtime'))
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData('moonlightipr'))
        QtWidgets.QApplication.processEvents()
        if panel.start.text() == 'Render':
            panel.start.click()
    except Exception:
        result['step3_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(25000, step4)


def step4():
    try:
        panel = panel_widget()
        result['moonlightipr'] = [panel.status.text(), panel.warnings.toPlainText()[:500]]
        panel.window().grab().save(str(out / 'moonlightipr_clusters.png'))
        modo.Scene().select(modo.Scene().item('Guides'))
        lx.eval('moonray.object.hair_mode 1')
        if panel.start.text() == 'Render':
            panel.start.click()
    except Exception:
        result['step4_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(25000, step5)


def step5():
    try:
        panel = panel_widget()
        result['moonlightipr_between'] = panel.status.text()
        panel.window().grab().save(str(out / 'moonlightipr_between.png'))
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        # The window's choices are shared with the user's own Modo: put back what was stored.
        for key in ('runtime', 'ipr'):
            if held[key]:
                panel.preferences.store.setValue(key, held[key])
            else:
                panel.preferences.store.remove(key)
    except Exception:
        result['step5_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(500, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(8000, step2)
