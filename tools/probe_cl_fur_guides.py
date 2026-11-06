# python
"""Command line: what Modo's Fur guides do, as Modo's own renderer draws them, for the kit to grow the same. A 1 x 1 patch
of quads ('Skin') wears a Fur material with short fibres standing straight up (0.1 long); five guide curves in the same
mesh leave the surface and curve over toward +X, 0.3 long. Rendered once for each guide mode (none, clump, normal =
Direction, dirlen = Direction + Length, shape, range), from the side and from above, and once with the guides in a
mesh of their own. What Modo holds (the guide channels, the fur's links to other items) is written down.
Writes test-results/fur-guides/ (report.json, <mode>-side.*.exr, <mode>-top.*.exr, guides.lxo)."""
import json
import math
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\fur-guides')
out.mkdir(parents=True, exist_ok=True)
report = {}
GUIDE_ROOTS = [(-0.3, -0.3), (0.3, -0.3), (0.0, 0.0), (-0.3, 0.3), (0.3, 0.3)]
MODES = os.environ.get('PROBE_MODES', 'none,clump,normal,dirlen,shape,range').split(',')


def guide(x, z, steps=7, length=0.3):
    """A guide from (x, 0, z): up at first, then over toward +X, as a quarter circle of this length; or with
    PROBE_GUIDE=tilt, straight, leaning 45 degrees toward +X."""
    if os.environ.get('PROBE_GUIDE') == 'tilt':
        return [(x + length * j / (steps - 1) * math.sqrt(.5), length * j / (steps - 1) * math.sqrt(.5), z) for j in range(steps)]
    radius = length / (math.pi / 2)
    return [(x + radius * (1 - math.cos(a)), radius * math.sin(a), z) for a in (math.pi / 2 * j / (steps - 1) for j in range(steps))]


def add_guides(mesh):
    with mesh.geometry as geo:
        polygons = geo.internalMesh.PolygonAccessor()
        for x, z in GUIDE_ROOTS:
            places = guide(x, z)
            storage = lx.object.storage('p', len(places))
            storage.set(tuple(geo.vertices.new(p).id for p in places))
            polygons.New(lx.symbol.iPTYP_LINE, storage, len(places), 0)


def links(item):
    found = {}
    for graph in ('shadeLoc', 'furGuide', 'furMesh', 'meshInst', 'source', 'deformers', 'chanMods'):
        try:
            forward = [i.name for i in item.itemGraph(graph).forward()]
            back = [i.name for i in item.itemGraph(graph).reverse()]
            if forward or back:
                found[graph] = [forward, back]
        except Exception:
            pass
    return found


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
    # The patch's polygons given a material as Modo's own command gives one (its mask made where Modo makes it), and
    # a Fur layer added into that mask as Add Layer adds one.
    # The guide curves first, so that the material is set on them as on the patch: guides on the base surface are
    # taken from its curves that wear the fur's material.
    add_guides(skin)
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
                       ('nrmJitter', 0.0), ('strays', 0.0), ('guideSurf', 1)):
        fur.channel(key).set(value)
    report['tree'] = [(c.name, c.type) for c in mask.children()]
    report['guide_channels'] = {k: fur.channel(k).get() for k in ('guides', 'guideRange', 'guideLength', 'guideBlend', 'angle', 'guideSurf', 'guideTag', 'guideType')}
    report['links_on_surface'] = links(fur)
    render_item = scene.renderItem
    for name, value in (('resX', 480), ('resY', 270), ('first', 1), ('last', 1)):
        render_item.channel(name).set(value)
    camera = scene.renderCamera
    poses = {'side': ((0.0, 0.25, 1.6), (-6.0, 0.0, 0.0)), 'top': ((0.0, 1.9, 0.0), (-90.0, 0.0, 0.0))}
    views = os.environ.get('PROBE_VIEWS', 'side').split(',')

    def every(prefix):
        for mode in MODES:
            fur.channel('guides').set(mode)
            for view in views:
                position, rotation = poses[view]
                camera.position.set(position)
                camera.rotation.set(rotation, degrees=True)
                render('%s-%s-%s' % (prefix, mode, view))
    # 1. Guides on the base surface, the curves wearing the fur's material as the patch does.
    MODES_SURFACE = [m for m in os.environ.get('PROBE_SURFACE_MODES', 'shape').split(',') if m]
    for mode in MODES_SURFACE:
        fur.channel('guides').set(mode)
        camera.position.set(poses['side'][0])
        camera.rotation.set(poses['side'][1], degrees=True)
        render('surface-tagged-%s-side' % mode)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'guides.lxo'))
    # 2. The guides in a mesh of their own, the Fur material told to take them from it.
    guides = scene.addMesh('Guides')
    add_guides(guides)
    fur.channel('guideSurf').set(0)
    lx.eval('select.item {%s} set' % fur.id)
    lx.eval('fur.setMesh name:{Guides}')
    report['links_with_item'] = links(fur)
    every('item')
    # PROBE_EXTRA: 'channel=value:mode;...', each rendered from every view with the guides of their own mesh.
    for extra in [e for e in os.environ.get('PROBE_EXTRA', '').split(';') if e]:
        setting, mode = extra.split(':')
        name, value = setting.split('=')
        held = fur.channel(name).get()
        fur.channel(name).set(float(value))
        fur.channel('guides').set(mode)
        for view in views:
            position, rotation = poses[view]
            camera.position.set(position)
            camera.rotation.set(rotation, degrees=True)
            render('extra-%s-%s-%s-%s' % (name, value, mode, view))
        fur.channel(name).set(held)
    report['rendered'] = sorted(p.name for p in out.glob('*.exr'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
