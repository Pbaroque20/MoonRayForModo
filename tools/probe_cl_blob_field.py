# python
"""Command line: how Modo's renderer shapes Blobs and Sprites, measured. Each experiment is a scene of Blob or Sprite
items over clouds of points in the XY plane, seen by an orthographic camera down -Z (16 m across 1600 x 800 pixels,
100 pixels a metre, the origin in the middle), rendered by Modo to <out>/<name>.exr (its alpha is what is measured by
tools/measure_blob_field.py). Experiments:
  levels   - one particle each, Radius 1, Level 0.1 0.25 0.5 0.75 0.9 at x = -6 -3 0 3 6
  pairs-a  - two particles each, Radius 1, Level 0.5, apart 0.8 1.2 1.6 centred at x = -5 0 5
  pairs-b  - the same, apart 1.0 1.4 1.8
  sizes    - Radius 1, Level 0.5, Size Random 50%: a row of eleven particles 1.4 apart
  sprites  - one particle each, Radius 1: (Density, Falloff) (1, 0) (1, 0.5) (1, 1) (0.25, 0.5) (4, 0.5)
  spritesb - Radius 1, Falloff 0.5, Density 1: Scattering 0, 0.5, 1, 2 and Luminous Density on
  sprites2 - (Radius, Falloff) (1, 0.1) (1, 0.25) (1, 0.75) (1, 0.9) (0.5, 0)
  space    - a source moved and scaled, a Blob item moved: which transform places the particles
  shade    - a sphere mesh beside a Blob of its size, without and with a Material: how a Blob is shaded
  sprites3 - Falloff 0.5: (Radius, Slices) (1, 1) (1, 2) (1, 8) (0.5, 3) (1.5, 3)
Writes <out>/report.json. MOONRAY_PROBE_OUT is the output folder; MOONRAY_PROBE_ONLY a comma list of experiments."""
import json
import math
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT') or r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-ab5779a40d6c39b81\test-results\blob-field')
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


def volume(scene, kind, name, points, **channels):
    source = cloud(scene, name + ' points', points)
    item = scene.addItem(kind, name=name)
    lx.eval('select.item {%s} set' % item.id)
    lx.eval('volume.particle {%s}' % source.id)
    for key, value in channels.items():
        item.channel(key).set(value)
    return item


def stage(name):
    lx.eval('scene.new')
    scene = modo.Scene()
    camera = scene.renderCamera
    camera.position.set((0.0, 0.0, 20.0))
    camera.rotation.set((0.0, 0.0, 0.0))
    for key, value in (('projType', 'ortho'), ('apertureX', 0.036), ('apertureY', 0.018), ('focalLen', 0.036), ('focusDist', 16.0)):
        camera.channel(key).set(value)
    render_item = scene.renderItem
    for key, value in (('resX', 1600), ('resY', 800), ('first', 1), ('last', 1)):
        render_item.channel(key).set(value)
    return scene


def render(scene, name):
    try:
        lx.eval('!scene.saveAs {%s} $LXOB false' % (out / (name + '.lxo')))
        lx.eval('!render.animation {%s} openexr' % (out / name))
        report[name] = sorted(p.name for p in out.glob(name + '*'))
    except Exception:
        report[name + ' error'] = traceback.format_exc()
    save()


def experiment(name):
    return not only or name in only


try:
    if experiment('levels'):
        scene = stage('levels')
        for i, level in enumerate((0.1, 0.25, 0.5, 0.75, 0.9)):
            volume(scene, 'blob', 'Blob %d' % i, [(-6.0 + 3.0 * i, 0.0, 0.0)], radius=1.0, level=level)
        render(scene, 'levels')
    for name, apart in (('pairs-a', (0.8, 1.2, 1.6)), ('pairs-b', (1.0, 1.4, 1.8))):
        if experiment(name):
            scene = stage(name)
            for i, d in enumerate(apart):
                x = -5.0 + 5.0 * i
                volume(scene, 'blob', 'Blob %d' % i, [(x - d / 2, 0.0, 0.0), (x + d / 2, 0.0, 0.0)], radius=1.0, level=0.5)
            render(scene, name)
    if experiment('sizes'):
        scene = stage('sizes')
        volume(scene, 'blob', 'Blob', [(-7.0 + 1.4 * i, 0.0, 0.0) for i in range(11)], radius=0.6, level=0.5, sizeRand=0.5)
        render(scene, 'sizes')
    if experiment('sprites'):
        scene = stage('sprites')
        for i, (density, falloff) in enumerate(((1.0, 0.0), (1.0, 0.5), (1.0, 1.0), (0.25, 0.5), (4.0, 0.5))):
            volume(scene, 'sprite', 'Sprite %d' % i, [(-6.0 + 3.0 * i, 0.0, 0.0)], radius=1.0, density=density, falloff=falloff)
        render(scene, 'sprites')
    if experiment('spritesb'):
        scene = stage('spritesb')
        for i, (scattering, luminous) in enumerate(((0.0, 0), (0.5, 0), (1.0, 0), (2.0, 0), (1.0, 1))):
            volume(scene, 'sprite', 'Sprite %d' % i, [(-6.0 + 3.0 * i, 0.0, 0.0)], radius=1.0, scattering=scattering, lumDens=luminous)
        render(scene, 'spritesb')
    if experiment('sprites2'):
        scene = stage('sprites2')
        for i, (radius, falloff) in enumerate(((1.0, 0.1), (1.0, 0.25), (1.0, 0.75), (1.0, 0.9), (0.5, 0.0))):
            volume(scene, 'sprite', 'Sprite %d' % i, [(-6.0 + 3.0 * i, 0.0, 0.0)], radius=radius, falloff=falloff)
        render(scene, 'sprites2')
    if experiment('sprites3'):
        scene = stage('sprites3')
        for i, (radius, slices) in enumerate(((1.0, 1), (1.0, 2), (1.0, 8), (0.5, 3), (1.5, 3))):
            volume(scene, 'sprite', 'Sprite %d' % i, [(-6.0 + 3.0 * i, 0.0, 0.0)], radius=radius, slices=slices)
        render(scene, 'sprites3')
    if experiment('space'):
        # Where the particles stand: a source moved (x -4, scaled 2), a Blob item moved (x 4), both at the local origin.
        scene = stage('space')
        moved = volume(scene, 'blob', 'Source moved', [(0.0, 0.0, 0.0), (0.5, 0.0, 0.0)], radius=0.5, level=0.5)
        source = modo.Mesh(scene.item('Source moved points'))
        source.position.set((-4.0, 0.0, 0.0))
        source.scale.set((2.0, 2.0, 2.0))
        other = volume(scene, 'blob', 'Blob moved', [(0.0, 0.0, 0.0)], radius=0.5, level=0.5)
        modo.LocatorSuperType(other).position.set((4.0, 1.0, 0.0))
        render(scene, 'space')
    if experiment('shade'):
        # How a Blob is shaded: a sphere mesh (Default material, x -3) beside a Blob of the same size with no Material
        # (x 0) and one whose Material is Default (x 3); lit by the scene's light and a sun turned toward the camera.
        scene = stage('shade')
        mesh = scene.addMesh('Sphere')
        with mesh.geometry as geo:
            rings, around, r = 24, 48, 0.5
            top = geo.vertices.new((-3.0, r, 0.0))
            bottom = geo.vertices.new((-3.0, -r, 0.0))
            grid = []
            for i in range(1, rings):
                a = math.pi * i / rings
                grid.append([geo.vertices.new((-3.0 + r * math.sin(a) * math.cos(2 * math.pi * j / around), r * math.cos(a),
                                                r * math.sin(a) * math.sin(2 * math.pi * j / around))) for j in range(around)])
            for j in range(around):
                k = (j + 1) % around
                geo.polygons.new([top, grid[0][k], grid[0][j]])
                geo.polygons.new([bottom, grid[-1][j], grid[-1][k]])
                for i in range(rings - 2):
                    geo.polygons.new([grid[i][j], grid[i][k], grid[i + 1][k], grid[i + 1][j]])
        size = 0.5 / math.sqrt(1.0 - 0.5 ** (1.0 / 3.0))
        volume(scene, 'blob', 'Blob plain', [(0.0, 0.0, 0.0)], radius=size, level=0.5)
        tagged = volume(scene, 'blob', 'Blob default', [(3.0, 0.0, 0.0)], radius=size, level=0.5)
        tagged.channel('material').set('Default')
        render(scene, 'shade')
except Exception:
    report['error'] = traceback.format_exc()
    save()
