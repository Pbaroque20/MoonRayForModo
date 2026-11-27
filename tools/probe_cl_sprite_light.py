# python
"""Command line: how bright Modo draws a Sprite's fog, lit by the sun alone (no environment light, Global Illumination
off), for setting the kit's Sprite fog against MoonRay's (particles.SPRITE_BRIGHTNESS). Scenes (MOONRAY_PROBE_ONLY):
  puff   - one puff (Radius 1, Falloff 0.5, Density 1, Scattering 1), orthographic front view, 100 pixels a metre
  puff4  - the same at Scattering 0.25 (does brightness follow Scattering?)
  slab   - 1,500 puffs in a slab (Radius 0.35, Falloff 0.5, Density 0.5) above a floor, seen from the front a little below
  lum    - the puff with Luminous Density on and the sun off (how much it glows by itself)
  lum2   - the same at Scattering 0.5 and Density 2
  tex5, tex10 - the puff with Texture Displacement (texAmplitude) 0.5 (Modo's default) and 1.0
  big    - one puff of Radius 3 at Texture Displacement 0.5, to see the texture's grain
  r45    - the puff at Radius 0.45 (the reference scene's)
  persp45, persp1 - a puff of Radius 0.45 or 1 at (0, 1, 0) seen by the reference scene's perspective camera
  pair   - two puffs, one behind the other as the sun sees them: is the far one shaded by the near one?
Each is rendered to <out>/<name>.exr and saved as <out>/<name>.lxo (for tools/probe_cl_blob_render.py to export).
MOONRAY_PROBE_OUT is the folder."""
import json
import math
import os
import pathlib
import random
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or 'test-results/sprite-light')
out.mkdir(parents=True, exist_ok=True)
only = [name for name in os.environ.get('MOONRAY_PROBE_ONLY', '').split(',') if name]
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def cloud(scene, name, points):
    mesh = scene.addMesh(name)
    with mesh.geometry as geo:
        for p in points:
            geo.vertices.new(p)
    return mesh


def sprite(scene, name, points, **channels):
    source = cloud(scene, name + ' points', points)
    item = scene.addItem('sprite', name=name)
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('volume.particle {%s}' % source.id)
    channels.setdefault('texAmplitude', 0.0)
    for key, value in channels.items():
        item.channel(key).set(value)
    return item


def stage(ortho=True):
    lx.eval('scene.new')
    scene = modo.Scene()
    camera = scene.renderCamera
    if ortho:
        camera.position.set((0.0, 0.0, 20.0))
        camera.rotation.set((0.0, 0.0, 0.0))
        for key, value in (('projType', 'ortho'), ('apertureX', 0.036), ('apertureY', 0.018), ('focalLen', 0.072), ('focusDist', 16.0)):
            camera.channel(key).set(value)
        size = (800, 400)
    else:
        camera.position.set((0.0, 1.6, 8.0))
        camera.rotation.set((0.08, 0.0, 0.0))
        size = (960, 540)
    render_item = scene.renderItem
    for key, value in (('resX', size[0]), ('resY', size[1]), ('first', 1), ('last', 1), ('globEnable', 0)):
        render_item.channel(key).set(value)
    # No light from the environment: its colours black.
    for item in scene.items('environment'):
        try:
            item.channel('intensity').set(0.0)
        except Exception as exc:
            report.setdefault('environment', []).append(str(exc))
    return scene


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
    if run('puff'):
        scene = stage()
        sprite(scene, 'Puff', [(0.0, 0.0, 0.0)], radius=1.0, falloff=0.5, density=1.0, scattering=1.0)
        render(scene, 'puff')
    if run('puff4'):
        scene = stage()
        sprite(scene, 'Puff', [(0.0, 0.0, 0.0)], radius=1.0, falloff=0.5, density=1.0, scattering=0.25)
        render(scene, 'puff4')
    for name, scattering, density in (('lum', 1.0, 1.0), ('lum2', 0.5, 2.0)):
        if run(name):
            scene = stage()
            sprite(scene, 'Puff', [(0.0, 0.0, 0.0)], radius=1.0, falloff=0.5, density=density, scattering=scattering, lumDens=1)
            for sun in scene.items('sunLight'):
                sun.channel('render').set('off')
            render(scene, name)
    for name, amplitude, radius in (('tex5', 0.5, 1.0), ('tex10', 1.0, 1.0), ('big', 0.5, 1.9)):
        if run(name):
            scene = stage()
            sprite(scene, 'Puff', [(0.0, 0.0, 0.0)], radius=radius, falloff=0.5, density=1.0, scattering=1.0, texAmplitude=amplitude)
            render(scene, name)
    if run('r45'):
        scene = stage()
        sprite(scene, 'Puff', [(0.0, 0.0, 0.0)], radius=0.45, falloff=0.5, density=1.0, scattering=1.0)
        render(scene, 'r45')
    for name, radius in (('persp45', 0.45), ('persp1', 1.0)):
        if run(name):
            scene = stage(ortho=False)
            camera = scene.renderCamera
            camera.position.set((0.0, 2.2, 6.5))
            camera.rotation.set((-0.22, 0.0, 0.0))
            sprite(scene, 'Puff', [(0.0, 1.0, 0.0)], radius=radius, falloff=0.5, density=1.0, scattering=1.0)
            render(scene, name)
    if run('pair'):
        # The sun's direction in a new scene, then a second puff 2.2 m back toward it from the first.
        scene = stage()
        sun = list(scene.items('sunLight'))[0]
        m = modo.Matrix4(sun.channel('worldMatrix').get())
        back = [m[2][0], m[2][1], m[2][2]]
        report['sun z axis'] = back
        sprite(scene, 'Near', [(-2.0, 0.0, 0.0)], radius=1.0, falloff=0.5, density=1.0)
        sprite(scene, 'Shaded', [(2.0, 0.0, 0.0), (2.0 + 2.2 * back[0], 2.2 * back[1], 2.2 * back[2])], radius=1.0, falloff=0.5, density=1.0)
        render(scene, 'pair')
    if run('slab'):
        rng = random.Random(7)
        scene = stage(ortho=False)
        sprite(scene, 'Cloud', [(rng.uniform(-2.5, 2.5), rng.uniform(2.0, 2.6), rng.uniform(-1.5, 0.5)) for _ in range(1500)],
               radius=0.35, falloff=0.5, density=0.5)
        floor = scene.addMesh('Floor')
        with floor.geometry as geo:
            corners = [geo.vertices.new(p) for p in ((-8, 0, -8), (8, 0, -8), (8, 0, 8), (-8, 0, 8))]
            geo.polygons.new([corners[0], corners[3], corners[2], corners[1]])
        render(scene, 'slab')
except Exception:
    report['error'] = traceback.format_exc()
save()
