# python
"""Command line: which surfaces the guard against too fine a displaced cut counts (host.modo_cut_refused), against what
Modo's displaced render cache then holds, at a Displacement Rate of PROBE_RATE pixels (3) at 1920 x 1080.
- mask: two 10 x 10 m planes, the Displacement layer in a group mask for the first alone. The render cache lists the
  layer for both; the guard is to count the first only.
- proxy: a Scene Proxy of a scene whose own Shader Tree displaces its plane, the scene rendered having no Displacement
  layer of its own. The guard is to count the proxy's plane.
For each: the old count (by the render cache's layers and the scene's own Displacement layers), the guard's count
(host.estimate_sample, displacement_budget.modo_cut) and the triangles of Modo's displaced reading of the surfaces.
Writes <PROBE_OUT>/report.json."""
import json
import math
import os
import pathlib
import time
import traceback

import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\displacement-scope'))
out.mkdir(parents=True, exist_ok=True)
bumps = pathlib.Path(os.environ.get('PROBE_BUMPS', str(out / 'bumps.png')))
rate = float(os.environ.get('PROBE_RATE', 3.0))
report = {'rate': rate}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def plane(name, x, segments=4, size=10.0):
    lx.eval('item.create mesh')
    mesh = modo.Scene().selected[-1]
    mesh.name = name
    with mesh.geometry as geometry:
        points = [[geometry.vertices.new((x - size / 2 + size * i / segments, 0.0, -size / 2 + size * j / segments))
                   for i in range(segments + 1)] for j in range(segments + 1)]
        for j in range(segments):
            for i in range(segments):
                geometry.polygons.new((points[j][i], points[j + 1][i], points[j + 1][i + 1], points[j][i + 1]), reversed=False)
    return mesh


def displace_layer(scene, parent, index=None):
    render = scene.renderItem
    lx.eval('clip.addStill {%s}' % bumps)
    clip = next(c for c in scene.items('videoStill') if pathlib.Path(c.channel('filename').get()).name == bumps.name)
    layer = scene.addItem('imageMap', name='bumps (Image)')
    if index is None:
        shader = next(i for i in render.children() if i.type == 'defaultShader')
        index = max(0, shader.parentIndex - 1)
    layer.setParent(parent, index)
    layer.channel('effect').set('displace')
    graph = lx.object.ItemGraph(lx.object.Scene(layer._item.Context()).GraphLookup('shadeLoc'))
    graph.AddLink(layer._item, clip._item)
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('planar')
    locator.channel('projAxis').set(1)
    locator.scale.set((2.5, 2.5, 2.5))
    return layer


def setup(scene, position, pitch):
    render = scene.renderItem
    render.channel('resX').set(1920)
    render.channel('resY').set(1080)
    render.channel('dispRate').set(rate)
    base = next(i for i in render.children() if i.type == 'advancedMaterial')
    base.channel('displace').set(0.1)
    camera = scene.renderCamera
    camera.position.set(position)
    camera.rotation.set((-math.radians(pitch), 0.0, 0.0))


def measure(label):
    scene = modo.Scene()
    from moonray_modo import host, evaluated, displacement_budget
    moment = lx.service.Selection().GetTime()
    row = {}
    camera = scene.renderCamera
    matrix = host.world_matrix(camera, moment)
    cam = {'matrix': matrix, 'focal_mm': float(camera.channel('focalLen').get()) * 1000,
           'film_mm': float(camera.channel('apertureX').get()) * 1000, 'projection': 'persp'}
    token = host._MODO_DISPLACES.set(False)
    try:
        plain = evaluated.capture(moment, displaced=False)
    finally:
        host._MODO_DISPLACES.reset(token)
    names = {item.id: item.name for item in scene.items()}
    row['listed'] = [(names.get(s['source_item'], s['source_item']), list(s.get('layers') or []), s.get('shading_scene')) for s in plain['surfaces']]
    old_layers = host.displacing_layers(scene)
    row['old_count'] = round(displacement_budget.modo_dicing(plain, old_layers, cam, 1920, 1080, rate)) if old_layers else None
    began = time.perf_counter()
    kept = host.estimate_sample(scene, moment)
    row['estimate_seconds'] = round(time.perf_counter() - began, 3)
    row['guard_count'] = round(displacement_budget.modo_cut(kept['sample'], displacement_budget.View(cam, 1920, 1080), rate))
    row['guard_surfaces'] = kept['surfaces']
    row['guard_owners'] = [(names.get(o[0], o[0]), o[2]) for o in kept['owners']]
    if row['guard_count'] > displacement_budget.MODO_DISPLACED_TRIANGLES:
        # Refused: Modo's displaced reading is not made (at 1 pixel the plane's took 22 GB in Modo).
        report[label] = row
        save()
        return
    shown = evaluated.capture(moment, displaced=True)
    shown = dict(shown, surfaces=[dict(s) for s in shown['surfaces']])
    evaluated.proxies(shown, scene, moment, [], displaced=True)
    per = {}
    for surface in shown['surfaces']:
        prototype = shown['prototypes'].get(str(surface['source_id'])) or {}
        made = sum(displacement_budget.triangles(segment['faces']) for segment in prototype.get('segments') or () if segment.get('faces'))
        per[names.get(surface['source_item'], surface['source_item'])] = made
    row['modo_triangles'] = per
    evaluated.release_proxies()
    report[label] = row
    save()


try:
    # The mask case.
    scene = modo.Scene()
    first = plane('Masked', -6.0)
    plane('Other', 6.0)
    setup(scene, (0.0, 7.0, 15.0), 25.0)
    render = scene.renderItem
    lx.eval('select.item {%s} set' % render.id)
    lx.eval('shader.create mask')
    mask = [m for m in scene.items('mask', superType=False)][-1]
    lx.eval('select.item {%s} set' % mask.id)
    try:
        lx.eval('mask.setMesh {%s}' % first.name)
    except Exception:
        mask.itemGraph('shadeLoc') >> first.itemGraph('shadeLoc')
    report['mask_items'] = [i.name for i in mask.itemGraph('shadeLoc').forward()]
    displace_layer(scene, mask, 0)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'mask.lxo'))
    measure('mask')

    # The proxy case: a plane displaced by its own scene's Displacement layer, made a Scene Proxy as the Links panel
    # makes one (proxy.convert), the layer then taken out of the scene rendered, which has none of its own left.
    lx.eval('scene.new')
    scene = modo.Scene()
    setup(scene, (0.0, 1.7, 4.5), 12.0)
    held = plane('Proxied', 0.0)
    layer = displace_layer(scene, scene.renderItem)
    lx.eval('select.drop item')
    lx.eval('select.item {%s} set' % held.id)
    lx.eval('!proxy.convert item:{%s} filename:{%s} format:$LXOB tsurf:false' % (held.id, out / 'proxied.lxo'))
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('!item.delete')
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'proxy.lxo'))
    proxy = [i for i in scene.items('proxy')][0]
    report['proxy_channels'] = {c.name: str(c.get()) for c in proxy.channels() if c.name in ('scene', 'itemRender', 'itemPreview', 'render', 'visible')}
    report['proxy_layers_of_scene'] = sorted(__import__('moonray_modo.host', fromlist=['host']).displacing_layers(scene))
    measure('proxy')
except Exception:
    report['error'] = traceback.format_exc()
save()
