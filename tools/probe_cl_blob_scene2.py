# python
"""Command line: a second Blob and Sprite scene, with more particles and an animation, rendered by Modo's renderer for
comparison with the kit's (tools/probe_cl_blob_render.py, tools/render_particle_scene.py).
  Swarm: 3,000 points along a wound ring, a Blob over them (Radius 0.12, Level 0.5, Size Random 30 %); the points' mesh
         keyed to slide 1.5 m and turn 40 degrees from frame 1 to 10 (its particles move: velocities from their move).
  Cloud: 1,500 points in a slab above, a Sprite over them (Radius 0.35, Falloff 0.5, Density 0.5).
  Floor, camera and sun as the reference scene's. Frame 5 rendered (modo2.Final Color Output.0005.exr).
Also saved: perf.lxo, a Blob over 100,000 points in a ball (Radius 0.05), for timing the kit's reading.
MOONRAY_PROBE_OUT is the folder (default test-results/blob-scene2 in this checkout)."""
import json
import math
import os
import pathlib
import random
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-ab5779a40d6c39b81\test-results\blob-scene2')
out.mkdir(parents=True, exist_ok=True)
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def cloud(scene, name, points):
    mesh = scene.addMesh(name)
    with mesh.geometry as geo:
        for p in points:
            geo.vertices.new(p)
    return mesh


def particle_volume(kind, name, source, **channels):
    item = modo.Scene().addItem(kind, name=name)
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('volume.particle {%s}' % source.id)
    for key, value in channels.items():
        item.channel(key).set(value)
    return item


try:
    rng = random.Random(7)
    lx.eval('scene.new')
    scene = modo.Scene()
    ring = []
    for i in range(3000):
        t = 2 * math.pi * i / 3000
        wind = 14 * t
        ring.append((1.1 * math.cos(t) + 0.25 * math.cos(wind) * math.cos(t) + rng.uniform(-0.03, 0.03),
                     0.6 + 0.25 * math.sin(wind) + rng.uniform(-0.03, 0.03),
                     1.1 * math.sin(t) + 0.25 * math.cos(wind) * math.sin(t) + rng.uniform(-0.03, 0.03)))
    swarm = cloud(scene, 'Swarm points', ring)
    particle_volume('blob', 'Swarm', swarm, radius=0.12, level=0.5, sizeRand=0.3)
    slab = cloud(scene, 'Cloud points', [(rng.uniform(-2.5, 2.5), rng.uniform(2.0, 2.6), rng.uniform(-1.5, 0.5)) for _ in range(1500)])
    particle_volume('sprite', 'Cloud', slab, radius=0.35, falloff=0.5, density=0.5)
    # The swarm's points slide and turn from frame 1 to 10.
    fps = float(scene.fps)
    for frame, x, turn in ((1, -1.0, 0.0), (10, 0.5, math.radians(40))):
        lx.service.Selection().SetTime((frame) / fps)
        swarm.position.x.set(x, time=frame / fps, key=True)
        swarm.rotation.y.set(turn, time=frame / fps, key=True)
    floor = scene.addMesh('Floor')
    with floor.geometry as geo:
        corners = [geo.vertices.new(p) for p in ((-8, 0, -8), (8, 0, -8), (8, 0, 8), (-8, 0, 8))]
        geo.polygons.new([corners[0], corners[3], corners[2], corners[1]])
    camera = scene.renderCamera
    camera.position.set((0.0, 2.6, 7.0))
    camera.rotation.set((-0.26, 0.0, 0.0))
    render_item = scene.renderItem
    for name, value in (('resX', 960), ('resY', 540), ('first', 5), ('last', 5)):
        render_item.channel(name).set(value)
    lx.service.Selection().SetTime(5 / fps)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'blob_scene2.lxo'))
    report['saved'] = str(out / 'blob_scene2.lxo')
    save()
    if not os.environ.get('MOONRAY_PROBE_NO_RENDER'):
        lx.eval('!render.animation {%s} openexr' % (out / 'modo2'))
        report['rendered'] = sorted(p.name for p in out.glob('modo2*'))
    save()
    lx.eval('scene.new')
    scene = modo.Scene()
    ball = []
    while len(ball) < 100000:
        p = (rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))
        if p[0] ** 2 + p[1] ** 2 + p[2] ** 2 <= 1:
            ball.append((p[0] * 1.5, 1.6 + p[1] * 1.5, p[2] * 1.5))
    many = cloud(scene, 'Many points', ball)
    particle_volume('blob', 'Many', many, radius=0.05, level=0.5)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'perf.lxo'))
    report['perf'] = str(out / 'perf.lxo')
except Exception:
    report['error'] = traceback.format_exc()
save()
