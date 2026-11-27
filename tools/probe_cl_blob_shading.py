# python
"""Command line: how Modo's renderer lights a Blob, against a sphere mesh of the same size and material. Each scene: a
sphere mesh (x -1.5) and a lone-particle Blob of its size (x 1.5), Radius chosen so the blob is 0.5 across... 1 m wide,
seen by an orthographic camera down -Z (800 x 400, 100 pixels a metre). Experiments (MOONRAY_PROBE_ONLY, a comma list):
  direct      - the scene's Directional Light alone (Global Illumination off)
  noshadow    - the same, the light casting no shadows
  side        - the light from the side (+X), Global Illumination off: where the terminator falls
  area        - an Area Light alone (soft shadows), Global Illumination off: grain
  gi          - the Directional Light and Global Illumination on (as a default scene renders)
  front       - the Directional Light from the camera (turned 0, 0, 0), Global Illumination off
  back        - the Directional Light from behind (turned 0, 180, 0), Global Illumination off: lit from inside?
  point       - a Point Light between the camera and the items, Global Illumination off
  sprite-*    - a lone Sprite puff (Radius 1, Falloff 0.5, Density 1, Scattering 1, no texture) at x 1.5 in place of
                the Blob: -direct (the light, GI off), -dark (no light, GI off), -gi (the light, GI on),
                -sky (no light, GI on)
Renders <out>/<name>.exr and saves <out>/<name>.lxo; report.json lists the light's channels. MOONRAY_PROBE_OUT is the
output folder."""
import json
import math
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or 'test-results/blob-shading')
out.mkdir(parents=True, exist_ok=True)
only = [name for name in os.environ.get('MOONRAY_PROBE_ONLY', '').split(',') if name]
report = {}
R = 0.5


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def stage():
    lx.eval('scene.new')
    scene = modo.Scene()
    camera = scene.renderCamera
    camera.position.set((0.0, 0.0, 20.0))
    camera.rotation.set((0.0, 0.0, 0.0))
    for key, value in (('projType', 'ortho'), ('apertureX', 0.036), ('apertureY', 0.018), ('focalLen', 0.072), ('focusDist', 16.0)):
        camera.channel(key).set(value)
    render_item = scene.renderItem
    for key, value in (('resX', 800), ('resY', 400), ('first', 1), ('last', 1), ('globEnable', 0)):
        try:
            render_item.channel(key).set(value)
        except Exception as exc:
            report.setdefault('channel errors', []).append('%s %s' % (key, exc))
    mesh = scene.addMesh('Sphere')
    with mesh.geometry as geo:
        rings, around, cx = 48, 96, -1.5
        top = geo.vertices.new((cx, R, 0.0))
        bottom = geo.vertices.new((cx, -R, 0.0))
        grid = []
        for i in range(1, rings):
            a = math.pi * i / rings
            grid.append([geo.vertices.new((cx + R * math.sin(a) * math.cos(2 * math.pi * j / around), R * math.cos(a),
                                            R * math.sin(a) * math.sin(2 * math.pi * j / around))) for j in range(around)])
        for j in range(around):
            k = (j + 1) % around
            geo.polygons.new([top, grid[0][k], grid[0][j]])
            geo.polygons.new([bottom, grid[-1][j], grid[-1][k]])
            for i in range(rings - 2):
                geo.polygons.new([grid[i][j], grid[i][k], grid[i + 1][k], grid[i + 1][j]])
    source = scene.addMesh('Blob points')
    with source.geometry as geo:
        geo.vertices.new((1.5, 0.0, 0.0))
    blob = scene.addItem('blob', name='Blob')
    lx.eval('select.item {%s} set' % blob.id)
    lx.eval('volume.particle {%s}' % source.id)
    blob.channel('radius').set(R / math.sqrt(1.0 - 0.5 ** (1.0 / 3.0)))
    blob.channel('level').set(0.5)
    blob.channel('material').set('Default')
    light = [i for i in scene.items('sunLight')] + [i for i in scene.items('light')]
    return scene, blob, (light[0] if light else None)


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
    scene, blob, light = stage()
    report['light'] = {'type': light.type if light else None}
    if light is not None:
        chans = {}
        for c in light.channels():
            try:
                v = c.get()
                if not hasattr(v, '__class__') or 'Unknown' not in str(v):
                    chans[c.name] = v
            except Exception:
                pass
        report['light']['channels'] = chans
        for c in scene.items('defaultShader'):
            report['shader channels'] = {ch.name: str(ch.get()) for ch in c.channels() if 'Unknown' not in str(ch.get())}
    report['blob channels'] = {c.name: str(c.get()) for c in blob.channels() if 'Unknown' not in str(c.get())}
    save()
    if run('direct'):
        scene, blob, light = stage()
        render(scene, 'direct')
    if run('noshadow'):
        scene, blob, light = stage()
        light.channel('shadType').set('none')
        render(scene, 'noshadow')
    if run('side'):
        scene, blob, light = stage()
        modo.LocatorSuperType(light).rotation.set((0.0, math.radians(90.0), 0.0))
        render(scene, 'side')
    if run('area'):
        scene, blob, light = stage()
        light.channel('render').set('off')
        area = scene.addItem('areaLight', name='Area')
        modo.LocatorSuperType(area).position.set((0.0, 3.0, 4.0))
        modo.LocatorSuperType(area).rotation.set((math.radians(-35.0), 0.0, 0.0))
        for key, value in (('width', 2.0), ('height', 2.0), ('radiance', 6.0)):
            area.channel(key).set(value)
        render(scene, 'area')
    if run('gi'):
        scene, blob, light = stage()
        scene.renderItem.channel('globEnable').set(1)
        render(scene, 'gi')
    for name, turn in (('front', 0.0), ('back', 180.0)):
        if run(name):
            scene, blob, light = stage()
            modo.LocatorSuperType(light).rotation.set((0.0, math.radians(turn), 0.0))
            render(scene, name)
    if run('point'):
        scene, blob, light = stage()
        light.channel('render').set('off')
        point = scene.addItem('pointLight', name='Point')
        modo.LocatorSuperType(point).position.set((0.0, 1.0, 3.0))
        point.channel('radiance').set(10.0)
        render(scene, 'point')
    for name, lit, gi in (('sprite-direct', 1, 0), ('sprite-dark', 0, 0), ('sprite-gi', 1, 1), ('sprite-sky', 0, 1)):
        if run(name):
            scene, blob, light = stage()
            blob.channel('render').set('off')
            sprite = scene.addItem('sprite', name='Sprite')
            lx.eval('select.item {%s} set' % sprite.id)
            lx.eval('volume.particle {%s}' % scene.item('Blob points').id)
            for key, value in (('radius', 1.0), ('falloff', 0.5), ('density', 1.0), ('scattering', 1.0), ('texAmplitude', 0.0)):
                sprite.channel(key).set(value)
            if not lit:
                light.channel('render').set('off')
            scene.renderItem.channel('globEnable').set(gi)
            render(scene, name)
except Exception:
    report['error'] = traceback.format_exc()
save()
