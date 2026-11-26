# python
"""Command line: a 10 x 10 m plane displaced by an image (Modo's defaults otherwise: Displacement Rate 1 pixel, Minimum
Edge Length 100 um), seen by a camera standing on it at eye height, as an artist frames a ground. Written for MoonRay
as the kit writes it (as modeled, MoonRay displacing it: own-<rate>.rdla) and, with PROBE_EVALUATED=1, as Surfaces:
Modo evaluated geometry reads it (Modo's displaced render cache: evaluated-<rate>.rdla). PROBE_BUMPS the height image,
PROBE_SEGMENTS the plane's polygons along each side (1), PROBE_DISTANCE the material's displacement distance in metres
(0.1), PROBE_RATES Modo's Displacement Rates to write (1,3), PROBE_SIZE the render width (1920, at 16:9). Writes
<PROBE_OUT>/report.json with the render item's displacement channels and each scene's faces and mesh settings."""
import json
import math
import os
import pathlib
import time
import traceback

import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\displaced-plane'))
out.mkdir(parents=True, exist_ok=True)
bumps = pathlib.Path(os.environ.get('PROBE_BUMPS', str(out / 'bumps.png')))
segments = int(os.environ.get('PROBE_SEGMENTS', 1))
report = {'segments': segments}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


try:
    scene = modo.Scene()
    lx.eval('item.create mesh')
    mesh = scene.selected[-1]
    size = 10.0
    with mesh.geometry as geometry:
        points = [[geometry.vertices.new((-size / 2 + size * i / segments, 0.0, -size / 2 + size * j / segments))
                   for i in range(segments + 1)] for j in range(segments + 1)]
        for j in range(segments):
            for i in range(segments):
                geometry.polygons.new((points[j][i], points[j + 1][i], points[j + 1][i + 1], points[j][i + 1]), reversed=False)
    report['mesh'] = {'points': mesh.geometry.numVertices, 'polygons': mesh.geometry.numPolygons}
    render = scene.renderItem
    report['render_channels'] = {name: render.channel(name).get() for name in ('dispRate', 'dispRatio', 'edgeMin', 'dispSmooth', 'dispEnable')
                                 if render.channel(name) is not None}
    width = int(os.environ.get('PROBE_SIZE', 1920))
    render.channel('resX').set(width)
    render.channel('resY').set(width * 9 // 16)
    save()

    lx.eval('clip.addStill {%s}' % bumps)
    clip = next(c for c in scene.items('videoStill') if pathlib.Path(c.channel('filename').get()).name == bumps.name)
    base = next(i for i in render.children() if i.type == 'advancedMaterial')
    base.channel('displace').set(float(os.environ.get('PROBE_DISTANCE', 0.1)))
    shader = next(i for i in render.children() if i.type == 'defaultShader')
    layer = scene.addItem('imageMap', name='bumps (Image)')
    layer.setParent(render, max(0, shader.parentIndex - 1))
    layer.channel('effect').set('displace')
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, clip._item)
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('planar')
    locator.channel('projAxis').set(1)
    locator.scale.set((2.5, 2.5, 2.5))

    camera = scene.renderCamera
    # Standing at the plane's near edge, 1.7 m up, looking along it and a little down.
    camera.position.set((0.0, 1.7, 4.5))
    camera.rotation.set((-math.radians(12.0), 0.0, 0.0))
    save()

    from moonray_modo import host, rdla, displacement_budget
    for rate in [float(r) for r in os.environ.get('PROBE_RATES', '1,3').split(',')]:
        render.channel('dispRate').set(rate)
        kinds = ['own'] + (['evaluated'] if os.environ.get('PROBE_EVALUATED') == '1' else [])
        for kind in kinds:
            began = time.perf_counter()
            if kind == 'own':
                snapshot = host.snapshot(evaluated_geometry=False)
            else:
                with host.by_engine('moonray'):
                    snapshot = host.snapshot(evaluated_geometry=True)
            read = time.perf_counter() - began
            began = time.perf_counter()
            text = rdla.scene_text(snapshot, width, width * 9 // 16, 1, 0.0, str(out / ('%s-%g.exr' % (kind, rate))))
            written = time.perf_counter() - began
            (out / ('%s-%g.rdla' % (kind, rate))).write_text(text, encoding='utf-8')
            report['%s-%g' % (kind, rate)] = {
                'read_seconds': round(read, 2), 'rdla_seconds': round(written, 2), 'bytes': len(text),
                'faces': sum(len(m.get('faces') or []) for m in snapshot.get('meshes') or []),
                'points': sum(len(m.get('vertices') or []) for m in snapshot.get('meshes') or []),
                'displacement_rate': snapshot.get('displacement_rate'), 'min_edge': snapshot.get('displacement_min_edge'),
                'fallback': sum(1 for m in snapshot.get('meshes') or [] if m.get('displacement_fallback')),
                'verdicts': dict((str(k[2:5]), round(v)) for k, v in displacement_budget._VERDICTS.items()),
                'mesh_lines': [line.strip() for line in text.splitlines() if 'mesh_resolution' in line or 'adaptive_error' in line
                               and 'target' not in line],
                'displacements': [line for line in text.splitlines() if line.startswith('displacements[')],
                'warnings': snapshot.get('warnings')}
            save()
except Exception:
    report['error'] = traceback.format_exc()
save()
