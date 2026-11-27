# python
"""Command line: what Modo's Smooth Positions (render item dispSmooth) does to a displaced polygon cage. A 16-sided open
cylinder (radius 1, height 2, two rings) and a 16 x 8 polygon sphere (radius 1), displaced by an image a hundredth of a
millimetre (so that the cut is Modo's and the relief is nothing), read through Modo's displaced render cache with Smooth
Positions on and off. Writes <PROBE_OUT>/smooth-<0|1>.json: each mesh's cut points (and their normals where given), for
tools/fit_smooth_positions.py to fit against flat, Phong and PN-triangle surfaces."""
import json
import math
import os
import pathlib
import traceback

import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\smooth-positions'))
out.mkdir(parents=True, exist_ok=True)
bumps = pathlib.Path(os.environ['PROBE_BUMPS'])
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


def cylinder(segments=16, x=-1.6):
    points = [[x + math.sin(2 * math.pi * s / segments), -1.0 + r, math.cos(2 * math.pi * s / segments)] for r in range(3) for s in range(segments)]
    polygons = [[r * segments + s, r * segments + (s + 1) % segments, (r + 1) * segments + (s + 1) % segments, (r + 1) * segments + s]
                for r in range(2) for s in range(segments)]
    return points, polygons


def sphere(segments=16, rings=8, x=1.6):
    points = [[x, 1.0, 0.0]] + [[x + math.sin(math.pi * r / rings) * math.sin(2 * math.pi * s / segments), math.cos(math.pi * r / rings),
                                 math.sin(math.pi * r / rings) * math.cos(2 * math.pi * s / segments)]
                                for r in range(1, rings) for s in range(segments)] + [[x, -1.0, 0.0]]
    ring = lambda r, s: 1 + (r - 1) * segments + s % segments
    polygons = [[0, ring(1, s), ring(1, s + 1)] for s in range(segments)]
    polygons += [[ring(r, s), ring(r + 1, s), ring(r + 1, s + 1), ring(r, s + 1)] for r in range(1, rings - 1) for s in range(segments)]
    polygons += [[ring(rings - 1, s), len(points) - 1, ring(rings - 1, s + 1)] for s in range(segments)]
    return points, polygons


try:
    scene = modo.Scene()
    mesh('Cylinder', *cylinder())
    mesh('Sphere', *sphere())
    render = scene.renderItem
    render.channel('resX').set(960)
    render.channel('resY').set(540)
    render.channel('dispRate').set(float(os.environ.get('PROBE_RATE', 4.0)))
    lx.eval('clip.addStill {%s}' % bumps)
    clip = next(c for c in scene.items('videoStill') if pathlib.Path(c.channel('filename').get()).name == bumps.name)
    base = next(i for i in render.children() if i.type == 'advancedMaterial')
    base.channel('displace').set(0.00001)
    report['smoothing_angle'] = base.channel('smAngle').get() if base.channel('smAngle') is not None else None
    shader = next(i for i in render.children() if i.type == 'defaultShader')
    layer = scene.addItem('imageMap', name='bumps (Image)')
    layer.setParent(render, max(0, shader.parentIndex - 1))
    layer.channel('effect').set('displace')
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, clip._item)
    camera = scene.renderCamera
    camera.position.set((0.0, 0.0, 6.0))
    camera.rotation.set((0.0, 0.0, 0.0))
    names = {item.id: item.name for item in scene.items()}
    from moonray_modo import evaluated
    for smooth in (0, 1):
        render.channel('dispSmooth').set(smooth)
        data = evaluated.capture(lx.service.Selection().GetTime(), displaced=True, kept=False)
        found = {}
        for surface in data['surfaces']:
            prototype = data['prototypes'].get(str(surface['source_id'])) or {}
            rows = found.setdefault(names.get(surface['source_item'], surface['source_item']), {'points': [], 'normals': [], 'faces': 0})
            for segment in prototype.get('segments') or ():
                rows['points'] += [[float(v[0]), float(v[1]), float(v[2])] for v in segment['vertices']]
                if segment.get('normals'):
                    rows['normals'] += [[float(v[0]), float(v[1]), float(v[2])] for v in segment['normals']]
                rows['faces'] += len(segment['faces'])
        (out / ('smooth-%d.json' % smooth)).write_text(json.dumps(found))
        report['smooth-%d' % smooth] = {name: {'points': len(rows['points']), 'faces': rows['faces']} for name, rows in found.items()}
        save()
except Exception:
    report['error'] = traceback.format_exc()
save()
