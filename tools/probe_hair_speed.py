# python
"""Isolated GUI test: where the time goes when a scene with dense hair is drawn again.

Guides are put on a sphere and hair grown from them, as many strands a guide as it is first switched on with. The
scene is read and packed for MoonLightIPR, and written for MoonRay, twice each: the first time everything is made,
the second is what a re-render costs when nothing about the hair has changed. Each is timed and the functions that
took longest the second time are written down. PROBE_GUIDES is how many guides (default 300)."""
import cProfile
import io
import json
import math
import os
import pathlib
import pstats
import random
import time
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo')
out = root / 'test-results/hair-speed'
out.mkdir(parents=True, exist_ok=True)
result = {}
RADIUS = 0.5


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def timed(name, work, profile=False):
    profiler = cProfile.Profile() if profile and not os.environ.get('PROBE_PLAIN') else None
    started = time.time()
    made = profiler.runcall(work) if profiler else work()
    result[name] = round(time.time() - started, 3)
    if profiler:
        text = io.StringIO()
        pstats.Stats(profiler, stream=text).sort_stats('cumulative').print_stats(28)
        (out / (name + '.txt')).write_text(text.getvalue())
    save()
    return made


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
    from moonray_modo import host, moonlightipr_scene, rdla, native
    runtime = native.find_runtime(root / 'runtime/steady-0350-pool')
    first = timed('read_first', lambda: host.snapshot(refresh_materials=True), True)
    result['strands'] = sum(len(e.get('counts', ())) for e in first.get('extra_geometry', []))
    result['points'] = sum(len(e.get('vertices', ())) for e in first.get('extra_geometry', []))
    taken = timed('read_again', lambda: host.snapshot(refresh_materials=True), True)
    timed('pack_first', lambda: moonlightipr_scene.pack(taken, 960, 540, runtime=runtime), True)
    timed('pack_again', lambda: moonlightipr_scene.pack(taken, 960, 540, runtime=runtime), True)
    timed('write_first', lambda: rdla.scene_text(taken, 960, 540, 2, 0.5, str(out / 'hair.exr')), True)
    timed('write_again', lambda: rdla.scene_text(taken, 960, 540, 2, 0.5, str(out / 'hair.exr')), True)
except Exception:
    result['error2'] = traceback.format_exc()
save()
lx.eval('!app.quit')
