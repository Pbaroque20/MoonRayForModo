# python
"""Command line: hair grown from guides on a scalp (as tools/probe_hair_speed.py makes it), read by the scene reader
with the curves worked out by the geometry adapter (curves.cpp, the grower's strands kept as its run) and by Python:
the same MoonRay scene text, the same MoonLightIPR packing of every curve geometry, and how long each took.
PROBE_GUIDES is how many guides (default 300). Writes test-results/hair-native.json."""
import json
import math
import os
import pathlib
import random
import time
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
result = {}
RADIUS = 0.5
try:
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.sphere on')
    for name, value in (('cenX', 0), ('cenY', RADIUS), ('cenZ', 0), ('sizeX', RADIUS), ('sizeY', RADIUS), ('sizeZ', RADIUS)):
        lx.eval('tool.attr prim.sphere %s %s' % (name, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.sphere off')
    scene = modo.Scene()
    scalp = scene.selected[0]
    scalp.name = 'Scalp'
    guides = scene.addMesh('Guides')
    random.seed(5)
    with guides.geometry as g:
        polygons = g.internalMesh.PolygonAccessor()
        for i in range(int(os.environ.get('PROBE_GUIDES', '300'))):
            a, b = random.uniform(.05, 3.0), random.uniform(0, 2 * math.pi)
            normal = (math.sin(a) * math.cos(b), math.cos(a), math.sin(a) * math.sin(b))
            places = []
            for j in range(7):
                reach = RADIUS + .2 * j / 6.0
                places.append((normal[0] * reach, RADIUS + normal[1] * reach - .06 * (j / 6.0) ** 2, normal[2] * reach))
            storage = lx.object.storage('p', len(places))
            storage.set(tuple(g.vertices.new(place).id for place in places))
            polygons.New(lx.symbol.iPTYP_LINE, storage, len(places), 0)
    scene.select(guides)
    lx.eval('moonray.object.override 1')
    lx.eval('moonray.object.hair 1')
    from lxserv import moonray_commands as commands
    choices = commands.scalp_choices()
    lx.eval('moonray.object.hair_scalp %d' % next(i for i, (_, label) in enumerate(choices) if label == 'Scalp'))
    from moonray_modo import host, rdla, extra_geometry, moonlightipr_curves, hair_native
    held_shape, held_built = extra_geometry._shaped_natively, moonlightipr_curves.built_natively
    # The scalp's triangles, by the adapter and by the walk in Python.
    held_scalp = extra_geometry.scalp_natively
    start = time.perf_counter()
    fast = extra_geometry.scalp_triangles(scene, scalp.id)
    result['scalp_native_seconds'] = round(time.perf_counter() - start, 3)
    extra_geometry.scalp_natively = lambda *a: None
    try:
        start = time.perf_counter()
        slow = extra_geometry.scalp_triangles(scene, scalp.id)
        result['scalp_python_seconds'] = round(time.perf_counter() - start, 3)
    finally:
        extra_geometry.scalp_natively = held_scalp
    result['scalp_kind'] = type(fast).__name__
    result['scalp_triangles'] = len(slow)
    result['scalp_same'] = list(fast) == list(slow)
    texts, packed = {}, {}
    for label in ('native', 'python', 'native_again'):
        for cache in (extra_geometry.BATCHED, extra_geometry.PLACED, extra_geometry.WRITTEN, extra_geometry.SEEN,
                      moonlightipr_curves.BUILT, moonlightipr_curves.SAME):
            cache.clear()
        if label == 'python':
            extra_geometry._shaped_natively = lambda *a: None
            moonlightipr_curves.built_natively = lambda *a, **k: None
            extra_geometry.scalp_natively = lambda *a: None
        try:
            start = time.perf_counter()
            if label == 'python' and os.environ.get('PROBE_PROFILE'):
                import cProfile, io, pstats
                profiler = cProfile.Profile()
                snapshot = profiler.runcall(lambda: host.snapshot(refresh_materials=True))
                text = io.StringIO()
                pstats.Stats(profiler, stream=text).sort_stats('tottime').print_stats(14)
                result['python_profile'] = text.getvalue().splitlines()[-24:]
            else:
                snapshot = host.snapshot(refresh_materials=True)
            result.setdefault('read_seconds', {})[label] = round(time.perf_counter() - start, 3)
            curves = [e for e in snapshot.get('extra_geometry', []) if e.get('kind') == 'curves']
            result['strands'] = sum(len(e['counts']) for e in curves)
            result['points'] = sum(len(e['vertices']) for e in curves)
            result.setdefault('vertices_type', {})[label] = sorted({type(e['vertices']).__name__ for e in curves})
            start = time.perf_counter()
            packed[label] = [moonlightipr_curves.payload(e, 1) for e in curves]
            result.setdefault('pack_seconds', {})[label] = round(time.perf_counter() - start, 3)
            start = time.perf_counter()
            texts[label] = rdla.scene_text(snapshot, 320, 240, 2, 0.5, str(root / 'test-results/hair-native.exr'))
            result.setdefault('write_seconds', {})[label] = round(time.perf_counter() - start, 3)
        finally:
            extra_geometry._shaped_natively, moonlightipr_curves.built_natively = held_shape, held_built
            extra_geometry.scalp_natively = held_scalp
    result['grower_used'] = hair_native.program() is not None
    result['scene_text_same'] = texts['python'] == texts['native']
    result['packed_same'] = packed['python'] == packed['native']
    if not result['scene_text_same']:
        a, b = texts['native'].splitlines(), texts['python'].splitlines()
        result['first_difference'] = next(([i, a[i][:300], b[i][:300]] for i in range(min(len(a), len(b))) if a[i] != b[i]), [len(a), len(b)])
except Exception:
    result['error'] = traceback.format_exc()
(root / 'test-results/hair-native.json').write_text(json.dumps(result, indent=1, default=str))
