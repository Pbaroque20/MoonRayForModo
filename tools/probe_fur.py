# python
"""Isolated GUI test: a mesh that wears one of Modo's Fur materials renders with fur, in MoonLightIPR and in MoonRay.

A ball stands on a ground. The ball's material group is given a Fur material as Modo's Add Layer gives one, with its
fibres set long and far enough apart to see. What the plugin reads is written down (how many fibres, how long, how
wide), and the preview window is pictured with each engine."""
import json
import math
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore, QtWidgets

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/fur'
out.mkdir(parents=True, exist_ok=True)
result = {}
held = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def panel_widget():
    from moonray_modo.panel import Panel
    return next(w for w in QtWidgets.QApplication.allWidgets() if isinstance(w, Panel))


try:
    scene = modo.Scene()
    for name, tool, values in (('Ground', 'prim.cube', dict(cenY=-.05, sizeX=8, sizeY=.1, sizeZ=8)), ('Ball', 'prim.sphere', dict(cenY=.6, sizeX=.5, sizeY=.5, sizeZ=.5))):
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set %s on' % tool)
        for key, value in values.items():
            lx.eval('tool.attr %s %s %s' % (tool, key, value))
        lx.eval('tool.apply')
        lx.eval('tool.set %s off' % tool)
        scene.selected[0].name = name
        held[name] = scene.selected[0]
    mask = scene.addItem('mask', name='Pelt')
    mask.setParent(scene.renderItem, 0)
    # The group is for the ball's own material tag, as Modo's Polygon Set Material makes one.
    with held['Ball'].geometry as geometry:
        for polygon in geometry.polygons:
            polygon.materialTag = 'Pelt'
    mask.channel('ptyp').set('Material')
    mask.channel('ptag').set('Pelt')
    colour = scene.addItem('advancedMaterial', name='Pelt Material')
    colour.setParent(mask, 0)
    colour.channel('diffCol').set((.45, .28, .12))
    pelt = scene.addItem('furMaterial', name='Fur')
    pelt.setParent(mask, 1)
    for key, value in (('dist', .015), ('length', .12), ('width', .6), ('flex', .6)):
        pelt.channel(key).set(value)
    camera = scene.renderCamera
    camera.position.set((0.0, 1.0, 3.2))
    camera.rotation.set((-8.0, 0.0, 0.0), degrees=True)
    from moonray_modo import extra_geometry, properties
    warnings = []
    started = time.time()
    entries = extra_geometry.collect(scene, warnings, properties.scene_settings().get('production', {}))
    result['first_seconds'] = round(time.time() - started, 2)
    started = time.time()
    again = extra_geometry.collect(scene, [], properties.scene_settings().get('production', {}))
    result['again_seconds'] = round(time.time() - started, 2)
    result['same_lists_again'] = bool(entries) and entries[0]['vertices'] is again[0]['vertices']
    result['entries'] = [{'kind': e['kind'], 'strands': len(e['counts']), 'points': len(e['vertices']), 'material': e.get('material'), 'source': e.get('source_item') == held['Ball'].id,
                          'radius_mm': [round(1000 * e['radii'][0], 3), round(1000 * e['radii'][e['counts'][0] - 1], 3)] if e.get('radii') else round(1000 * e['radius'], 3),
                          'length_mm': round(1000 * sum(math.dist(a, b) for a, b in zip(e['vertices'], e['vertices'][1:e['counts'][0]])), 1)} for e in entries]
    result['warnings'] = warnings
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def engine(name, then, wait):
    try:
        panel = panel_widget()
        held.setdefault('stored', {key: panel.preferences.store.value(key, '') for key in ('runtime',)})
        held.setdefault('engine', panel.preview_engine.currentData())
        panel.preferences.set('runtime', str(root / 'runtime/steady-0350-pool'))
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(name))
        QtWidgets.QApplication.processEvents()
        if panel.start.text() == 'Render':
            panel.start.click()
    except Exception:
        result[name + '_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(wait, then)


def first():
    engine('moonlightipr', second, 25000)


def second():
    try:
        panel = panel_widget()
        result['moonlightipr'] = [panel.status.text(), panel.warnings.toPlainText()[:500]]
        panel.window().grab().save(str(out / 'moonlightipr.png'))
    except Exception:
        result['second_error'] = traceback.format_exc()
    engine('moonray', last, 100000)


def last():
    try:
        panel = panel_widget()
        result['moonray'] = [panel.status.text(), panel.warnings.toPlainText()[:500]]
        panel.window().grab().save(str(out / 'moonray.png'))
        if panel.start.text() == 'Stop':
            panel.start.click()
        panel.preview_engine.setCurrentIndex(panel.preview_engine.findData(held['engine']))
        for key, value in held['stored'].items():
            panel.preferences.store.setValue(key, value)
    except Exception:
        result['last_error'] = traceback.format_exc()
    save()
    lx.eval('!app.quit')


QtCore.QTimer.singleShot(5000, first)
