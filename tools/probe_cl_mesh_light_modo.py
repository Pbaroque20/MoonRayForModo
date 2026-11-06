# python
"""Command line: which way Modo's own renderer shines a Mesh Light. A floor, a camera below a panel and looking along
the floor, the panel a Mesh Light's Prototype with its polygon facing down (toward floor and camera) or up, and the
same scene lit by Modo's default directional light as a check that rendering works at all. Each rendered by Modo; the
average and the most of the picture written to test-results/mesh-light-modo/report.json."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\mesh-light-modo')
out.mkdir(parents=True, exist_ok=True)
result = {}


def quad(scene, name, size, height, down):
    mesh = scene.addMesh(name)
    with mesh.geometry as geo:
        corners = [(-size, height, -size), (size, height, -size), (size, height, size), (-size, height, size)]
        points = [geo.vertices.new(p) for p in corners]
        geo.polygons.new(points if down else list(reversed(points)))
        result.setdefault('normals', {})[name] = [round(v, 3) for v in geo.polygons[0].normal]
    return mesh


def case(label, kind, down=True, hidden=True, radiance=30.0, seen=True, look_up=False):
    lx.eval('scene.new')
    scene = modo.Scene()
    quad(scene, 'Floor', 4.0, 0.0, False)
    found = {}
    if kind == 'mesh':
        panel = quad(scene, 'Panel', 0.6, 2.0, down)
        if hidden:
            panel.channel('visible').set('off')
        lx.eval('item.create meshLight')
        light = next(i for i in scene.items('meshLight', superType=False))
        lx.eval('select.item {%s} set' % light.id)
        lx.eval('light.mesh mesh:{%s}' % panel.id)
        light.channel('radiance').set(radiance)
        light.channel('visCam').set(1 if seen else 0)
        found['prototype'] = [i.name for i in light.itemGraph('shadeLoc').forward()]
    for other in [i for i in scene.items('light') if i.type != 'meshLight']:
        if kind == 'mesh':
            other.channel('render').set('off')
    for environment in list(scene.items('environment')):
        if kind == 'mesh':
            scene.removeItems(environment)
    camera = scene.renderCamera
    camera.position.set((0.0, 1.0, 5.0) if not look_up else (0.0, 0.6, 2.5))
    camera.rotation.set((-0.12, 0.0, 0.0) if not look_up else (0.55, 0.0, 0.0))
    render = scene.renderItem
    for name, value in (('resX', 320), ('resY', 180), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    path = out / label
    lx.eval('!render.animation {%s} openexr' % str(path))
    found['files'] = [p.name for p in out.glob(label + '*.exr')]
    lx.eval('!scene.saveAs {%s} $LXOB false' % str(out / (label + '.lxo')))
    return found


import os
CASES = (('check', 'directional'), ('down', 'mesh', True), ('up', 'mesh', False), ('down-shown', 'mesh', True, False),
         ('up-shown', 'mesh', False, False), ('down-shown-unseen', 'mesh', True, False, 30.0, False),
         # Looking up at the panel: what the camera sees of a shown prototype, seen and unseen, and from its back.
         ('face-seen', 'mesh', True, False, 30.0, True, True), ('face-unseen', 'mesh', True, False, 30.0, False, True),
         ('back-seen', 'mesh', False, False, 30.0, True, True))
chosen = os.environ.get('PROBE_CASES')
for args in [c for c in CASES if not chosen or c[0] in chosen.split(',')]:
    try:
        result[args[0]] = case(*args)
    except Exception:
        result[args[0]] = 'error: ' + traceback.format_exc()[-1500:]
    (out / 'report.json').write_text(json.dumps(result, indent=2, default=str))
