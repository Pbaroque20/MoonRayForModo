# python
"""Command line: how Modo lays a Checker through its texture locator, one change at a time (the checker locator
mismatch from the layer-mask scene). A 2 x 2 plane at the origin facing a camera on +Z, a Material whose diffuse
colour is a Checker (black and white); its locator at the origin, then: scale 0.3 alone ('scale'), with a turn of 30
degrees about X ('rotx'), about Y ('roty'), about Z ('rotz'), and about X and Y ('rotxy'). Each rendered by Modo at
frame 1 alone to test-results/checker-variants/<name>.*.exr, with the locator's world matrix as the kit reads it and the
kit's rows for ModoProceduralMap in report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\checker-variants')
out.mkdir(parents=True, exist_ok=True)
report = {}
VARIANTS = (('scale', {}), ('rotx', {'rot.X': 30}), ('roty', {'rot.Y': 30}), ('rotz', {'rot.Z': 30}),
            ('rotxy', {'rot.X': 30, 'rot.Y': 30}), ('rotxyz', {'rot.X': 30, 'rot.Y': 30, 'rot.Z': 20}),
            ('axisy', {'rot.X': 30, 'rot.Y': 30, 'axis': 1}), ('axisz', {'rot.X': 30, 'rot.Y': 30, 'axis': 2}),
            ('moved', {'rot.X': 30, 'rot.Y': 30, 'rot.Z': 20, 'pos.X': .37, 'pos.Y': -.21, 'pos.Z': .13}),
            ('cube', {'rot.X': 30, 'rot.Y': 30, 'rot.Z': 20, 'pos.X': .37, 'type': 'cube'}))


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 400), ('resY', 400), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    plane = scene.addMesh('Plane')
    with plane.geometry as geo:
        points = [geo.vertices.new(p) for p in ((-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0))]
        geo.polygons.new(points)
    camera = scene.renderCamera
    camera.position.set((0.0, 0.0, 4.0))
    camera.rotation.set((0.0, 0.0, 0.0))
    group = scene.renderItem
    before = {i.id for i in scene.iterItems()}
    lx.eval('select.item {%s} set' % group.id)
    lx.eval('shader.create checker')
    checker = next(i for i in scene.iterItems() if i.id not in before and i.type == 'checker')
    checker.channel('effect').set('diffColor')
    locator = next(i for i in checker.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    report['projType'] = locator.channel('projType').get()
    report['tree'] = [(c.name, c.type) for c in group.children()]
    save()
    from moonray_modo.host import world_matrix, channel
    from moonray_modo import procedurals
    for name, turns in VARIANTS:
        lx.eval('select.item {%s} set' % locator.id)
        for key, value in (('pos.X', 0), ('pos.Y', 0), ('pos.Z', 0), ('rot.X', 0), ('rot.Y', 0), ('rot.Z', 0),
                           ('scl.X', .3), ('scl.Y', .3), ('scl.Z', .3)):
            lx.eval('transform.channel %s %s' % (key, turns.get(key, value)))
        locator.channel('projAxis').set(turns.get('axis', 0))
        checker.channel('type').set(turns.get('type', 'square'))
        data = procedurals.solid(checker, channel, lambda l, n, d=(0, 0, 0): list(d), True, world_matrix(locator))
        report[name] = {'axis': locator.channel('projAxis').get(), 'type': checker.channel('type').get(),
                        'world_matrix': list(world_matrix(locator)), 'rows': data['rows'] if data else None}
        save()
        lx.eval('!render.animation {%s} openexr' % str(out / name))
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'checker_variants.lxo'))
    report['files'] = sorted(p.name for p in out.glob('*.exr'))
except Exception:
    report['error'] = traceback.format_exc()
save()
