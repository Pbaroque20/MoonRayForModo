# python
"""Command line: a coarse displaced polygon cage as Modo renders it and as the kit hands it to the engines, with Modo's
Smooth Positions on and off. A 16-sided column and a 16 x 8 polygon ball (PROBE_SHAPES=box: a hard-edged box), raised 5 cm by an image projected from the
front, a Displacement Rate of 1 pixel at 640 x 360. Writes to <PROBE_OUT>: modo<frame>.exr (Modo's own render, Smooth
Positions on), smooth-<0|1>.rdla (the kit's MoonRay scene, as modeled) and smooth-<0|1>.mls (MoonLightIPR's payload,
for tools/check of it outside Modo), and report.json."""
import json
import math
import os
import pathlib
import traceback

import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\smooth-render'))
out.mkdir(parents=True, exist_ok=True)
bumps = pathlib.Path(os.environ['PROBE_BUMPS'])
runtime = os.environ.get('PROBE_RUNTIME', '')
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def mesh(name, points, polygons):
    lx.eval('item.create mesh')
    made = modo.Scene().selected[-1]
    made.name = name
    with made.geometry as geometry:
        vertices = [geometry.vertices.new(tuple(p)) for p in points]
        for polygon in polygons:
            geometry.polygons.new([vertices[k] for k in polygon], reversed=False)
    return made


def column(segments=16, x=-1.4):
    points = [[x + math.sin(2 * math.pi * s / segments), -1.0 + r, math.cos(2 * math.pi * s / segments)] for r in range(3) for s in range(segments)]
    polygons = [[r * segments + s, r * segments + (s + 1) % segments, (r + 1) * segments + (s + 1) % segments, (r + 1) * segments + s]
                for r in range(2) for s in range(segments)]
    return points, polygons


def ball(segments=16, rings=8, x=1.4):
    points = [[x, 1.0, 0.0]] + [[x + math.sin(math.pi * r / rings) * math.sin(2 * math.pi * s / segments), math.cos(math.pi * r / rings),
                                 math.sin(math.pi * r / rings) * math.cos(2 * math.pi * s / segments)]
                                for r in range(1, rings) for s in range(segments)] + [[x, -1.0, 0.0]]
    ring = lambda r, s: 1 + (r - 1) * segments + s % segments
    polygons = [[0, ring(1, s), ring(1, s + 1)] for s in range(segments)]
    polygons += [[ring(r, s), ring(r + 1, s), ring(r + 1, s + 1), ring(r, s + 1)] for r in range(1, rings - 1) for s in range(segments)]
    polygons += [[ring(rings - 1, s), len(points) - 1, ring(rings - 1, s + 1)] for s in range(segments)]
    return points, polygons


def box(size=2.4):
    h = size / 2
    points = [[x, y, z] for x in (-h, h) for y in (-h, h) for z in (-h, h)]
    polygons = [[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]]
    return points, polygons


try:
    scene = modo.Scene()
    if os.environ.get('PROBE_SHAPES', 'cage') == 'box':
        # A box of hard edges (Modo's 40 degree smoothing leaves its 90 degree edges sharp), turned to show two sides and
        # its top.
        made = mesh('Box', *box())
        made.rotation.set((math.radians(20.0), math.radians(35.0), 0.0))
    else:
        mesh('Column', *column())
        mesh('Ball', *ball())
    render = scene.renderItem
    render.channel('resX').set(640)
    render.channel('resY').set(360)
    render.channel('dispRate').set(1.0)
    render.channel('first').set(0)
    render.channel('last').set(0)
    lx.eval('clip.addStill {%s}' % bumps)
    clip = next(c for c in scene.items('videoStill') if pathlib.Path(c.channel('filename').get()).name == bumps.name)
    base = next(i for i in render.children() if i.type == 'advancedMaterial')
    base.channel('displace').set(0.05)
    shader = next(i for i in render.children() if i.type == 'defaultShader')
    layer = scene.addItem('imageMap', name='bumps (Image)')
    layer.setParent(render, max(0, shader.parentIndex - 1))
    layer.channel('effect').set('displace')
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, clip._item)
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('planar')
    locator.channel('projAxis').set(2)
    locator.scale.set((0.8, 0.8, 0.8))
    camera = scene.renderCamera
    camera.position.set((0.0, 0.0, 7.5))
    camera.rotation.set((0.0, 0.0, 0.0))
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'smooth.lxo'))
    if os.environ.get('PROBE_MODO_RENDER', '1') == '1':
        render.channel('dispSmooth').set(1)
        try:
            lx.eval('!render.animation {%s} openexr' % (out / 'modo'))
        except Exception as exc:
            report['modo_render'] = 'failed: %s' % exc
        report['rendered'] = sorted(p.name for p in out.glob('modo*'))
        save()
    from moonray_modo import host, rdla, moonlightipr_scene
    for smooth in (1, 0):
        render.channel('dispSmooth').set(smooth)
        snapshot = host.snapshot(evaluated_geometry=False)
        text = rdla.scene_text(snapshot, 640, 360, 4, 0.0, str(out / ('smooth-%d.exr' % smooth)))
        (out / ('smooth-%d.rdla' % smooth)).write_text(text, encoding='utf-8')
        payload, keys, warnings = moonlightipr_scene.pack(snapshot, 640, 360, environment=0, known=set(), samples=64,
                                                          denoise=False, runtime=runtime or None)
        (out / ('smooth-%d.mls' % smooth)).write_bytes(payload)
        report['smooth-%d' % smooth] = {'displacement_smooth': snapshot.get('displacement_smooth'), 'bytes': len(text),
                                        'mesh_lines': [l.strip() for l in text.splitlines() if 'mesh_resolution' in l],
                                        'mls_bytes': len(payload), 'warnings': snapshot.get('warnings')}
        save()
except Exception:
    report['error'] = traceback.format_exc()
save()
