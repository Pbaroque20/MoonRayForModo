# python
"""Command line: what Modo's Stretch does to a Blob and a Sprite, rendered by Modo (orthographic, down -Z, 100 pixels a
metre). Scenes (MOONRAY_PROBE_ONLY):
  still    - lone particles of a mesh (no velocity): Blobs Radius 0.5 at Stretch 0, 0.5, 1, 2 (x -4.5, -1.5, 1.5, 4.5)
  moving   - a Radial Emitter turned to throw particles along +X at 2 m/s (cone 0, no gravity, 3 a second) into a cached
             simulation; at frame 36 a Blob (Radius 0.3, Stretch 1) above and a Sprite (Radius 0.4, Stretch 1) below,
             and the same with Stretch 0 (moving0), for the shape along the velocity
Each is rendered to <out>/<name>.exr and saved as <out>/<name>.lxo; report.json holds the particles' positions and
velocities at the frame. MOONRAY_PROBE_OUT is the folder."""
import json
import math
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or 'test-results/particle-stretch')
out.mkdir(parents=True, exist_ok=True)
only = [name for name in os.environ.get('MOONRAY_PROBE_ONLY', '').split(',') if name]
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def stage(frame=1):
    lx.eval('scene.new')
    scene = modo.Scene()
    camera = scene.renderCamera
    camera.position.set((0.0, 0.0, 20.0))
    camera.rotation.set((0.0, 0.0, 0.0))
    for key, value in (('projType', 'ortho'), ('apertureX', 0.036), ('apertureY', 0.018), ('focalLen', 0.036), ('focusDist', 16.0)):
        camera.channel(key).set(value)
    for key, value in (('resX', 1600), ('resY', 800), ('first', frame), ('last', frame), ('globEnable', 0)):
        scene.renderItem.channel(key).set(value)
    return scene


def on(scene, kind, name, source, **channels):
    item = scene.addItem(kind, name=name)
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('volume.particle {%s}' % source.id)
    for key, value in channels.items():
        item.channel(key).set(value)
    return item


def render(scene, name):
    try:
        lx.eval('!scene.saveAs {%s} $LXOB false' % (out / (name + '.lxo')))
        lx.eval('!render.animation {%s} openexr' % (out / name))
        report[name] = sorted(p.name for p in out.glob(name + '*'))
    except Exception:
        report[name + ' error'] = traceback.format_exc()
    save()


def run(name):
    return not only or name in only


try:
    if run('still'):
        scene = stage()
        for i, stretch in enumerate((0.0, 0.5, 1.0, 2.0)):
            mesh = scene.addMesh('P%d' % i)
            with mesh.geometry as geo:
                geo.vertices.new((-4.5 + 3.0 * i, 0.0, 0.0))
            on(scene, 'blob', 'Blob %d' % i, mesh, radius=0.5 / math.sqrt(1.0 - 0.5 ** (1.0 / 3.0)), level=0.5, stretch=stretch)
        render(scene, 'still')
    for name, stretch, row, kind, radius in (('moving', 1.0, 0.0, 'blob', 0.3), ('moving0', 0.0, 0.0, 'blob', 0.3),
                                             ('movingsprite', 1.0, 0.0, 'sprite', 0.4), ('movingsprite0', 0.0, 0.0, 'sprite', 0.4)):
        if not run(name):
            continue
        scene = stage(36)
        made = []
        if True:
            before = {i.id for i in scene.items()}
            lx.eval('item.create radialEmitter')
            new = [i for i in scene.items() if i.id not in before]
            emitter = next(i for i in new if i.type == 'radialEmitter')
            sim = next(i for i in new if i.type == 'particleSim')
            modo.LocatorSuperType(emitter).position.set((-6.0, row, 0.0))
            # The emitter throws along its +Y: turned -90 degrees about Z, along +X.
            modo.LocatorSuperType(emitter).rotation.set((0.0, 0.0, math.radians(-90.0)))
            for key, value in (('rate', 3.0), ('velocity', 2.0), ('velocitySpread', 0.0), ('angle', 0.0), ('type', 'uniform')):
                try:
                    emitter.channel(key).set(value)
                except Exception as exc:
                    report.setdefault('channel errors', []).append('%s %s' % (key, exc))
            sim.channel('gravEnable').set(0)
            extra = {'texAmplitude': 0.0} if kind == 'sprite' else {'level': 0.5}
            made.append(on(scene, kind, '%s stretch' % kind, sim, radius=radius, stretch=stretch, **extra))
        lx.eval('!simulate 0.0 2.0')
        lx.service.Selection().SetTime(36 / float(scene.fps))
        from moonray_modo import particles
        held = {}
        for item in made:
            got = particles.read(item, 36 / float(scene.fps))
            held[item.name] = {'positions': [round(v, 3) for v in got['positions'][:12]], 'velocities': [round(v, 3) for v in (got['velocities'] or [])[:12]],
                               'count': len(got['ids'])} if got else None
        report[name + ' particles'] = held
        render(scene, name)
except Exception:
    report['error'] = traceback.format_exc()
save()
