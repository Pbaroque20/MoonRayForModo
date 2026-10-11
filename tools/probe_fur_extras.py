# python
"""Isolated GUI test: the Fur material's curls, clumps, kink, frizz and weight maps are grown, in both engines.

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
out = root / 'test-results/fur-extras'
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
    lx.eval('select.typeFrom item')
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    for key, value in dict(cenY=-.05, sizeX=8, sizeY=.1, sizeZ=8).items():
        lx.eval('tool.attr prim.cube %s %s' % (key, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    # Three balls: curled; tufted and kinked; and one whose fur is thinned by a weight map and frizzed, with its
    # group tied to the item itself rather than to a material tag.
    looks = (('Curly', -1.1, dict(curls=.8, curlRadius=1.0), (.5, .3, .12)),
             ('Tufted', 0.0, dict(clumps=.9, clumpSize=.12, kinkAmp=.6), (.2, .2, .22)),
             ('Thinned', 1.1, dict(frizAmp=.5, densityMap='Thin', lengthMap='Thin'), (.6, .55, .45)))
    for name, x, values, colour in looks:
        lx.eval('select.typeFrom item')
        lx.eval('item.create mesh')
        lx.eval('tool.set prim.sphere on')
        for key, value in dict(cenX=x, cenY=.6, sizeX=.4, sizeY=.4, sizeZ=.4).items():
            lx.eval('tool.attr prim.sphere %s %s' % (key, value))
        lx.eval('tool.apply')
        lx.eval('tool.set prim.sphere off')
        ball = scene.selected[0]
        ball.name = name
        held[name] = ball
        mask = scene.addItem('mask', name=name)
        mask.setParent(scene.renderItem, 0)
        with ball.geometry as geometry:
            if name == 'Thinned':
                # Fur on its near half only, and shorter toward the edge of it.
                weights = geometry.vmaps.addWeightMap('Thin')
                for vertex in geometry.vertices:
                    weights[vertex.index] = (max(0.0, min(1.0, vertex.position[2] / .4 + .2)),)
            else:
                for polygon in geometry.polygons:
                    polygon.materialTag = name
        if name == 'Thinned':
            scene.select(mask)
            try:
                mask.itemGraph('shadeLoc').connectInput(ball)
                if not mask.itemGraph('shadeLoc').forward():
                    ball.itemGraph('shadeLoc').connectInput(mask)
                result['item_mask'] = [target.name for target in mask.itemGraph('shadeLoc').forward()]
            except Exception:
                result['item_mask_error'] = traceback.format_exc()
        else:
            mask.channel('ptyp').set('Material')
            mask.channel('ptag').set(name)
        surface = scene.addItem('advancedMaterial', name=name + ' Material')
        surface.setParent(mask, 0)
        surface.channel('diffCol').set(colour)
        pelt = scene.addItem('furMaterial', name=name + ' Fur')
        pelt.setParent(mask, 1)
        for key, value in dict(dict(dist=.012, length=.14, width=.6, flex=.3), **values).items():
            pelt.channel(key).set(value)
    camera = scene.renderCamera
    camera.position.set((0.0, 1.0, 4.0))
    camera.rotation.set((-6.0, 0.0, 0.0), degrees=True)
    from moonray_modo import extra_geometry, properties
    names_of = {held[name].id: name for name in held}
    warnings = []
    started = time.time()
    from moonray_modo import host
    taken = host.snapshot(refresh_materials=True)
    entries = [e for e in taken['extra_geometry'] if e['kind'] == 'curves']
    warnings = [w for w in taken['warnings'] if 'Fur' in w]
    result['materials'] = sorted(taken['materials'])
    result['mesh_materials'] = sorted({(names_of.get(m.get('source_item') or str(m.get('identity', '')).split('|')[0]), m.get('material')) for m in taken['meshes']}, key=str)
    result['first_seconds'] = round(time.time() - started, 2)
    names = {held[name].id: name for name in held}
    result['entries'] = [{'of': names.get(e.get('source_item')), 'strands': len(e['counts']), 'joints': e['counts'][0], 'material': e.get('material')} for e in entries]
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
