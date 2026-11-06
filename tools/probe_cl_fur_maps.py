# python
"""Command line: what a Fur material's Vector VMap and width map do, as Modo's own renderer draws them. The 1 x 1 patch
of tools/probe_cl_fur_guides.py (fibres 0.1 long, straight up), given a vector map ('FurVector', Modo's VECT kind) and
a weight map ('FurWidth') and rendered from the side and from above, once for each case: 'plain', 'vector-lean'
((0.3, 0.3, 0) at every point), 'vector-short' ((0, 0.05, 0)), 'vector-half' (the lean on the left half, zero on the
right) and 'width-ramp' (weight 0 at the left edge to 1 at the right). Writes test-results/fur-maps/."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\fur-maps')
out.mkdir(parents=True, exist_ok=True)
report = {}
CASES = os.environ.get('PROBE_CASES', 'plain,vector-lean,vector-short,vector-half,width-ramp').split(',')


def render(label):
    lx.eval('!render.animation {%s} openexr' % str(out / label))


try:
    scene = modo.Scene()
    skin = scene.addMesh('Skin')
    with skin.geometry as geo:
        n = 10
        grid = [[geo.vertices.new((-0.5 + i / n, 0.0, -0.5 + j / n)) for i in range(n + 1)] for j in range(n + 1)]
        for j in range(n):
            for i in range(n):
                geo.polygons.new([grid[j][i], grid[j + 1][i], grid[j + 1][i + 1], grid[j][i + 1]])
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
                       ('nrmJitter', 0.0), ('strays', 0.0)):
        fur.channel(key).set(value)

    def fill(name, kind, value_of):
        """A map of this kind on the patch, each point given value_of(position)."""
        with skin.geometry as geo:
            maps = geo.vmaps
            found = [m for m in maps if m.name == name]
            vmap = found[0] if found else (maps.addWeightMap(name) if kind == 'weight' else maps.addMap(lx.symbol.i_VMAP_VECTOR, name))
            for vertex in geo.vertices:
                vmap[vertex.index] = value_of(vertex.position)
        return name

    render_item = scene.renderItem
    for name, value in (('resX', 480), ('resY', 270), ('first', 1), ('last', 1)):
        render_item.channel(name).set(value)
    camera = scene.renderCamera
    poses = {'side': ((0.0, 0.25, 1.6), (-6.0, 0.0, 0.0)), 'top': ((0.0, 1.9, 0.0), (-90.0, 0.0, 0.0))}
    for case in CASES:
        fur.channel('vectorMap').set('')
        fur.channel('widthMap').set('')
        if case == 'vector-lean':
            fur.channel('vectorMap').set(fill('FurVector', 'vector', lambda p: (0.3, 0.3, 0.0)))
        elif case == 'vector-short':
            fur.channel('vectorMap').set(fill('FurVector', 'vector', lambda p: (0.0, 0.05, 0.0)))
        elif case == 'vector-half':
            fur.channel('vectorMap').set(fill('FurVector', 'vector', lambda p: (0.3, 0.3, 0.0) if p[0] < 0 else (0.0, 0.0, 0.0)))
        elif case == 'width-ramp':
            fur.channel('widthMap').set(fill('FurWidth', 'weight', lambda p: (p[0] + 0.5,)))
        report.setdefault('maps', {})[case] = [fur.channel('vectorMap').get(), fur.channel('widthMap').get()]
        for view, (position, rotation) in poses.items():
            camera.position.set(position)
            camera.rotation.set(rotation, degrees=True)
            render('%s-%s' % (case, view))
    with skin.geometry as geo:
        report['vmaps'] = [(m.name, str(m.map_type)) for m in geo.vmaps]
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'maps.lxo'))
    report['rendered'] = sorted(p.name for p in out.glob('*.exr'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
