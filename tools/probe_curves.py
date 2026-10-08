# python
"""Isolated GUI test: a mesh's curves as tubes. Line polygons and a spline, the object override's envelope and UVs, thousands at once."""
import json
import math
import pathlib
import random
import time
import traceback
import lx
import modo
from PySide2 import QtCore

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/curves'
out.mkdir(parents=True, exist_ok=True)
result = {}
COUNT = 3000

try:
    from moonray_modo import extra_geometry, options, properties, rdla
    scene = modo.Scene()
    mesh = scene.addMesh('Strands')
    random.seed(2)
    with mesh.geometry as g:
        polygons = g.internalMesh.PolygonAccessor()

        def polygon(kind, places):
            storage = lx.object.storage('p', len(places))
            storage.set(tuple(g.vertices.new(place).id for place in places))
            polygons.New(kind, storage, len(places), 0)
        # A spline through four points, then strands that are lines already.
        polygon(lx.symbol.iPTYP_CURVE, [(x, 2 + .2 * math.sin(x * 3), 0) for x in (0, .3, .6, .9)])
        for i in range(COUNT):
            a = random.uniform(0, 2 * math.pi)
            x, z = math.cos(a), math.sin(a)
            polygon(lx.symbol.iPTYP_LINE, [(x * (1 + .05 * j), .1 * j, z * (1 + .05 * j)) for j in range(8)])
    result['polygons'] = len(mesh.geometry.polygons)
    controls = properties.scene_settings().get('production', {})
    started = time.time()
    plain = extra_geometry.collect(scene, [], controls)
    result['collect_seconds'] = round(time.time() - started, 2)
    result['plain'] = [(e['identity'].split('|', 1)[1], len(e['counts']), len(e['vertices']), e['radius'], 'radii' in e, len(e.get('uvs', [])))
                       for e in plain]
    scene.select(mesh)
    values = options.object_values(properties.read(mesh))
    values.update(override=True, curve_root_width=40.0, curve_tip_width=0.0, curve_envelope=2.0, curve_samples=4)
    properties.write(mesh, options.object_values(values))
    shaped = extra_geometry.collect(scene, [], controls)
    entry = shaped[0]
    result['shaped'] = [(len(e['counts']), len(e['vertices']), len(e.get('radii', [])), len(e.get('uvs', []))) for e in shaped]
    result['first_strand_radii'] = [round(v, 5) for v in entry['radii'][:entry['counts'][0]]]
    result['first_strand_uvs'] = [[round(c, 3) for c in v] for v in entry['uvs'][:entry['counts'][0]]]
    result['query'] = [lx.eval('moonray.object.curves ?'), lx.eval('moonray.object.curve_root_width ?')]
    snapshot = {'camera': {'matrix': [1, 0, 0, 0, 0, .9, -.44, 0, 0, .44, .9, 0, 0, 2.6, 4.2, 1], 'focal_mm': 50.0, 'film_mm': 36.0},
                'materials': {'': {'color': [.7, .5, .3], 'roughness': .5}}, 'meshes': [], 'extra_geometry': shaped,
                'lights': [{'kind': 'DistantLight', 'identity': 'sun', 'name': 'Sun', 'color': [1, 1, 1], 'intensity': 3.0, 'angle': 2.0,
                            'matrix': [1, 0, 0, 0, 0, .7, .7, 0, 0, -.7, .7, 0, 0, 0, 0, 1]}],
                'environments': [], 'width': 480, 'height': 360, 'warnings': []}
    started = time.time()
    text = rdla.scene_text(snapshot, 480, 360, 2, 0.2, str(out / 'curves.exr'))
    first = time.time() - started
    started = time.time()
    rdla.scene_text(snapshot, 480, 360, 2, 0.2, str(out / 'curves.exr'))
    result['text_seconds'] = [round(first, 3), round(time.time() - started, 3)]
    (out / 'curves.rdla').write_text(text, encoding='utf-8')
    values['curves'] = False
    properties.write(mesh, options.object_values(values))
    result['off'] = len(extra_geometry.collect(scene, [], controls))
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str))
QtCore.QTimer.singleShot(1500, lambda: lx.eval('!app.quit'))
