# python
"""GUI: pictures of the Fur material's guides and maps for the README, Modo's renderer beside MoonRay.

The scene of tools/probe_cl_fur_guides.py and tools/probe_cl_fur_maps.py in one: a 1 x 1 patch of quads ('Skin') wears a
Fur material of short fibres standing straight up; five guide curves in a mesh of their own ('Guides') leave the surface
and curve over toward +X; the patch carries a vector map leaning every fibre, one leaning only the left half (nothing on
the right), and a width map from 0 at the left edge to 1 at the right. Each case is rendered by Modo
(<case>-modo.png) and then by the preview window in MoonRay XPU (<case>-moonray.png). Writes test-results/fur-readme/."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo
from PySide2 import QtCore

out = pathlib.Path(os.environ.get('PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\fur-readme')
out.mkdir(parents=True, exist_ok=True)
result = {'steps': []}
GUIDE_ROOTS = [(-0.3, -0.3), (0.3, -0.3), (0.0, 0.0), (-0.3, 0.3), (0.3, 0.3)]
POSES = {'side': ((0.0, 0.25, 1.6), (-6.0, 0.0, 0.0)), 'top': ((0.0, 1.9, 0.0), (-90.0, 0.0, 0.0))}
# (name, guide mode, vector map, width map, view)
CASES = [('guides-none', 'none', '', '', 'side'), ('guides-direction', 'normal', '', '', 'side'),
         ('guides-shape', 'shape', '', '', 'side'), ('guides-range', 'range', '', '', 'side'),
         ('map-none', 'none', '', '', 'side'), ('map-vector', 'none', 'FurVector', '', 'side'),
         ('map-vector-half', 'none', 'FurVectorHalf', '', 'side'), ('map-width', 'none', '', 'FurWidth', 'top')]


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def guide(x, z, steps=7, length=0.3):
    import math
    radius = length / (math.pi / 2)
    return [(x + radius * (1 - math.cos(a)), radius * math.sin(a), z) for a in (math.pi / 2 * j / (steps - 1) for j in range(steps))]


def setup(case):
    """The fur and the camera set for a case, through commands (this runs from Qt timers too)."""
    name, mode, vector, width, view = case
    lx.eval('item.channel guides {%s} item:{%s}' % (mode, held['fur']))
    lx.eval('item.channel vectorMap {%s} item:{%s}' % (vector, held['fur']))
    lx.eval('item.channel widthMap {%s} item:{%s}' % (width, held['fur']))
    position, rotation = POSES[view]
    lx.eval('select.item {%s} set' % held['camera'])
    for axis, value in zip('XYZ', position):
        lx.eval('transform.channel pos.%s %s' % (axis, value))
    for axis, value in zip('XYZ', rotation):
        lx.eval('transform.channel rot.%s %s' % (axis, value))
    lx.eval('select.drop item')


held = {}
try:
    scene = modo.Scene()
    skin = scene.addMesh('Skin')
    with skin.geometry as geo:
        n = 10
        grid = [[geo.vertices.new((-0.5 + i / n, 0.0, -0.5 + j / n)) for i in range(n + 1)] for j in range(n + 1)]
        for j in range(n):
            for i in range(n):
                geo.polygons.new([grid[j][i], grid[j + 1][i], grid[j + 1][i + 1], grid[j][i + 1]])
    with skin.geometry as geo:
        maps = geo.vmaps
        for map_name, kind, value_of in (('FurVector', 'vector', lambda p: (0.3, 0.3, 0.0)),
                                         ('FurVectorHalf', 'vector', lambda p: (0.3, 0.3, 0.0) if p[0] < 0 else (0.0, 0.0, 0.0)),
                                         ('FurWidth', 'weight', lambda p: (p[0] + 0.5,))):
            vmap = maps.addWeightMap(map_name) if kind == 'weight' else maps.addMap(lx.symbol.i_VMAP_VECTOR, map_name)
            for vertex in geo.vertices:
                vmap[vertex.index] = value_of(vertex.position)
    lx.eval('select.item {%s} set' % skin.id)
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial Skin {0.6 0.45 0.3} 0.8 0.04 true false')
    lx.eval('select.type item')
    mask = next(m for m in scene.items('mask', superType=False) if m.channel('ptag').get() == 'Skin')
    before = {i.id for i in scene.iterItems()}
    lx.eval('select.item {%s} set' % mask.id)
    lx.eval('shader.create furMaterial')
    fur = next(i for i in scene.iterItems() if i.id not in before and i.type == 'furMaterial')
    for key, value in (('dist', .008), ('length', .1), ('width', .5), ('flex', 0.0), ('growthJitter', 0.0), ('sclJitter', 0.0),
                       ('nrmJitter', 0.0), ('strays', 0.0), ('guideSurf', 0)):
        fur.channel(key).set(value)
    guides = scene.addMesh('Guides')
    with guides.geometry as geo:
        polygons = geo.internalMesh.PolygonAccessor()
        for x, z in GUIDE_ROOTS:
            places = guide(x, z)
            storage = lx.object.storage('p', len(places))
            storage.set(tuple(geo.vertices.new(p).id for p in places))
            polygons.New(lx.symbol.iPTYP_LINE, storage, len(places), 0)
    lx.eval('select.item {%s} set' % fur.id)
    lx.eval('fur.setMesh name:{Guides}')
    render_item = scene.renderItem
    for name, value in (('resX', 960), ('resY', 540), ('first', 1), ('last', 1)):
        render_item.channel(name).set(value)
    held['fur'] = fur.id
    held['camera'] = scene.renderCamera.id
    for case in CASES:
        setup(case)
        lx.eval('!render.animation {%s} PNG' % str(out / (case[0] + '-modo')))
    result['modo'] = sorted(p.name for p in out.glob('*-modo*.png'))
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'fur_readme.lxo'))
    save()
    lx.eval('moonray.open')
except Exception:
    result['error'] = traceback.format_exc()
save()


def panel_widget():
    from moonray_modo.panel import live_panels
    return live_panels()[0]


def render(index):
    if index >= len(CASES):
        return finish()
    case = CASES[index]
    try:
        setup(case)
        p = panel_widget()
        if index == 0:
            p.preferences.set('preview_fraction', 1)
            p._store(execution_mode='xpu')
            p.preview_engine.setCurrentIndex(p.preview_engine.findData('moonray'))
        p.render_once()
        began = time.monotonic()

        def wait():
            try:
                q = panel_widget()
                if (getattr(q, '_rendering', False) and time.monotonic() - began < 240) or time.monotonic() - began < 6:
                    QtCore.QTimer.singleShot(1500, wait); return

                def grab():
                    q.preview.image.save(str(out / (case[0] + '-moonray.png')))
                    result['steps'].append([case[0], q.status.text(), q.image_info.text(), q.render_timing.text()])
                    save(); render(index + 1)
                QtCore.QTimer.singleShot(3000, grab)
            except Exception:
                result[case[0] + '_wait_error'] = traceback.format_exc(); save(); render(index + 1)
        QtCore.QTimer.singleShot(2000, wait)
    except Exception:
        result[case[0] + '_error'] = traceback.format_exc(); save(); render(index + 1)


def finish():
    try:
        panel_widget().stop()
    except Exception:
        result['finish_error'] = traceback.format_exc()
    save()
    QtCore.QTimer.singleShot(2000, lambda: lx.eval('!app.quit'))


QtCore.QTimer.singleShot(8000, lambda: render(0))
