# python
"""Command line: a surface Grid and Dots as Modo's own renderer lays them, against the plugin's (procedurals.sample,
the pattern baked into the image MoonRay, XPU2 and MoonLightIPR lay on by UV). A 2 x 2 plane (prim.plane, its UV map
0 to 1 across it) at the origin facing a camera on +Z (square 36 mm film, 50 mm lens, 4 units away), a Material with
no diffuse and a luminous Grid or Dots (black and white), or an image whose colour is its own coordinates, on it, no lights: Modo's picture is the pattern itself. Each
case is rendered to <out>/modo_<case>.exr, with the scene as the plugin reads it (<case>.json: host.snapshot) and
writes it for MoonRay (<case>.rdla, rendering moonray_<case>.exr) for tools/check_surface_procedurals.py.

PROBE_OUT is the folder (test-results/surface-procedurals by default); PROBE_CASES a comma-separated list of cases."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\surface-procedurals'))
out.mkdir(parents=True, exist_ok=True)
ONLY = [c for c in os.environ.get('PROBE_CASES', '').split(',') if c]
SIZE = 320
# name: (kind, projType, locator size, extra locator channels, layer channels)
CASES = [
    ('uv_grid_square', 'grid', 'uv', 1, {'wrapU': 3.0, 'wrapV': 3.0}, {'type': 'square', 'lineWidth': .2, 'transWidth': .3}),
    ('uv_grid_line', 'grid', 'uv', 1, {'wrapU': 3.0, 'wrapV': 3.0}, {'type': 'line', 'lineWidth': .2, 'transWidth': .3}),
    ('uv_grid_triangle', 'grid', 'uv', 1, {'wrapU': 3.0, 'wrapV': 3.0}, {'type': 'triangle', 'lineWidth': .1, 'transWidth': .1}),
    ('uv_grid_hexagon', 'grid', 'uv', 1, {'wrapU': 3.0, 'wrapV': 3.0}, {'type': 'hexagon', 'lineWidth': .1, 'transWidth': .1}),
    ('uv_grid_hard', 'grid', 'uv', 1, {'wrapU': 3.0, 'wrapV': 3.0}, {'type': 'square', 'lineWidth': .3, 'transWidth': 0.0}),
    ('uv_dots_square', 'dots', 'uv', 1, {'wrapU': 3.0, 'wrapV': 3.0}, {'type': 'square', 'dotWidth': .6, 'transWidth': .3}),
    ('uv_dots_hexagon', 'dots', 'uv', 1, {'wrapU': 3.0, 'wrapV': 3.0}, {'type': 'hexagon', 'dotWidth': .6, 'transWidth': .3}),
    ('uv_grid_square_t1', 'grid', 'uv', 1, {'wrapU': 3.0, 'wrapV': 3.0}, {'type': 'square', 'lineWidth': .2, 'transWidth': .1}),
    ('uv_grid_square_w1', 'grid', 'uv', 1, {}, {'type': 'square', 'lineWidth': .2, 'transWidth': .3}),
    ('uv_grid_square_bias', 'grid', 'uv', 1, {'wrapU': 2.0, 'wrapV': 3.0}, {'type': 'square', 'lineWidth': .15, 'transWidth': .2, 'bias': .3, 'gain': .7}),
    ('uv_grid_uvrot', 'grid', 'uv', 1, {'wrapU': 2.0, 'wrapV': 3.0, 'uvRotation': 30.0}, {'type': 'triangle', 'lineWidth': .1, 'transWidth': .1}),
    ('planar_grid_wrap', 'grid', 'planar', .5, {'wrapU': 2.0, 'wrapV': 3.0, 'uvRotation': 30.0}, {'type': 'triangle', 'lineWidth': .1, 'transWidth': .1}),
    # An image (its colour its own coordinates, uv_sq.exr in the folder) under the same UV changes.
    ('uv_image_wrap', 'image', 'uv', 1, {'wrapU': 2.0, 'wrapV': 3.0}, {}),
    ('uv_image_uvrot', 'image', 'uv', 1, {'uvRotation': 30.0}, {}),
    ('planar_grid_square', 'grid', 'planar', .5, {}, {'type': 'square', 'lineWidth': .2, 'transWidth': .3}),
    ('planar_grid_line', 'grid', 'planar', .5, {}, {'type': 'line', 'lineWidth': .2, 'transWidth': .3}),
    ('planar_grid_triangle', 'grid', 'planar', .5, {}, {'type': 'triangle', 'lineWidth': .1, 'transWidth': .1}),
    ('planar_dots_square', 'dots', 'planar', .5, {}, {'type': 'square', 'dotWidth': .6, 'transWidth': .3}),
    ('planar_dots_hexagon', 'dots', 'planar', .5, {}, {'type': 'hexagon', 'dotWidth': .6, 'transWidth': .3}),
]
LAYER_CHANNELS = {'grid': ('type', 'lineWidth', 'transWidth', 'bias', 'gain'), 'dots': ('type', 'dotWidth', 'transWidth', 'bias', 'gain'), 'image': ()}
report = {'cases': {}}
if ONLY and (out / 'report.json').is_file():
    # Only some cases again: the others' entries kept.
    report = json.loads((out / 'report.json').read_text())
    report.pop('error', None)


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str), encoding='utf-8')


try:
    from moonray_modo import host, rdla
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', SIZE), ('resY', SIZE), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    for light in scene.items('sunLight'):
        light.channel('render').set('off')
    environment = next(iter(scene.items('environment')))
    envmat = next((i for i in environment.children() if i.type == 'envMaterial'), None)
    if envmat is not None:
        envmat.channel('type').set('constant')
        for axis in 'RGB':
            envmat.channel('zenColor.' + axis).set(0.0)
    camera = scene.renderCamera
    camera.position.set((0.0, 0.0, 4.0))
    camera.rotation.set((0.0, 0.0, 0.0))
    for channel_name, value in (('focalLen', .05), ('apertureX', .036), ('apertureY', .036)):
        camera.channel(channel_name).set(value)
    mesh = scene.addMesh('Plane')
    geo = mesh.geometry
    uvmap = geo.vmaps.addMap(lx.symbol.i_VMAP_TEXTUREUV, 'Texture')
    points = [geo.vertices.new(p) for p in ((-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0))]
    polygon = geo.polygons.new(points)
    for point, value in zip(points, ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))):
        polygon.setUV(value, point, uvmap)
    geo.setMeshEdits()
    material = next(i for i in scene.items('advancedMaterial'))
    for channel_name, value in (('diffAmt', 0.0), ('specAmt', 0.0), ('reflAmt', 0.0), ('radiance', 1.0)):
        try:
            material.channel(channel_name).set(value)
        except Exception:
            pass
    report['uv_maps'] = [m.name for m in mesh.geometry.vmaps.uvMaps]
    layers = {}
    for name, kind, projection, size, extra, channels in CASES:
        if ONLY and name not in ONLY:
            continue
        entry = {}
        try:
            if kind not in layers:
                before = {i.id for i in scene.iterItems()}
                lx.eval('select.item {%s} set' % render.id)
                if kind == 'image':
                    lx.eval('clip.addStill {%s}' % str(out / 'uv_sq.exr'))
                    clip = scene.items('videoStill')[-1]
                    lx.eval('item.create imageMap')
                    layers[kind] = scene.selected[0]
                    lx.eval('texture.parent {%s} %d item:{%s}' % (render.id, len(render.children()), layers[kind].id))
                    lx.eval('select.item {%s} set' % layers[kind].id)
                    lx.eval('texture.setIMap {%s}' % clip.id)
                else:
                    lx.eval('shader.create %s' % kind)
                    layers[kind] = next(i for i in scene.iterItems() if i.id not in before and i.type == kind)
                layers[kind].channel('effect').set('lumiColor')
            layer = layers[kind]
            for other_kind, other in layers.items():
                other.channel('enable').set(other_kind == kind)
            locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
            locator.channel('projType').set(projection)
            locator.channel('projAxis').set(2)
            if projection == 'uv':
                locator.channel('uvMap').set(report['uv_maps'][0] if report['uv_maps'] else 'Texture')
            locator.position.set((0, 0, 0))
            locator.rotation.set((0, 0, 0))
            locator.scale.set((size, size, size))
            for channel_name, default in (('wrapU', 1.0), ('wrapV', 1.0), ('uvRotation', 0.0)):
                value = extra.get(channel_name, default)
                locator.channel(channel_name).set(value * 3.141592653589793 / 180 if channel_name == 'uvRotation' else value)
            for channel_name in LAYER_CHANNELS[kind]:
                layer.channel(channel_name).set(channels.get(channel_name, .5 if channel_name in ('bias', 'gain') else None))
            entry['layer'] = {c: str(layer.channel(c).get()) for c in LAYER_CHANNELS[kind]}
            entry['locator'] = {c: str(locator.channel(c).get()) for c in ('projType', 'projAxis', 'wrapU', 'wrapV', 'uvRotation', 'uvMap')}
            entry['matrix'] = host.world_matrix(locator)
            lx.eval('!render.animation {%s} openexr' % str(out / ('modo_%s' % name)))
            snapshot = host.snapshot()
            (out / ('%s.rdla' % name)).write_text(rdla.scene_text(snapshot, SIZE, SIZE, 4, 0.0, str(out / ('moonray_%s.exr' % name))), encoding='utf-8')
            kept = {k: v for k, v in snapshot.items() if not k.startswith('_')}
            (out / ('%s.json' % name)).write_text(json.dumps(kept, default=str), encoding='utf-8')
            entry['warnings'] = snapshot.get('warnings', [])[:6]
        except Exception:
            entry['error'] = traceback.format_exc()[-2500:]
        report['cases'][name] = entry
        save()
except Exception:
    report['error'] = traceback.format_exc()
save()
