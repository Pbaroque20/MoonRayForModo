# python
"""Command line: Modo's physical sky, alone and under an environment image or Grid at half opacity, as Modo renders it
and as the plugin writes it for MoonRay, seen by a 90-degree perspective camera in the six directions of a cube's faces
(<case>_v0 .. _v5: -Z, -X, +Z, +X, up, down), the sun turned so its disc is in view. Writes modo_<label>.exr,
<label>.rdla (rendering moonray_<label>.exr), <label>.json (the scene as the plugin reads it, for MoonLightIPR) and
report.json in tools/probe_cl_environment_projections.py's form, so that tools/check_environment_projections.py renders
and compares them.

PROBE_OUT is the folder (test-results/physical-sky-views by default; the image is uv_code.exr in it); PROBE_CASES a
comma-separated list of cases."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\physical-sky-views'))
out.mkdir(parents=True, exist_ok=True)
ONLY = [c for c in os.environ.get('PROBE_CASES', '').split(',') if c]
SIZE = 160
VIEWS = ((0, 0, 0), (0, 90, 0), (0, 180, 0), (0, 270, 0), (90, 0, 0), (-90, 0, 0))
# name: (sun rotation degrees XYZ, layer on top or None)
CASES = [
    ('sky', (-25, 60, 0), None),
    ('sky_east', (-15, -50, 0), None),
    ('sky_image', (-25, 60, 0), 'image'),
    ('sky_grid', (-25, 60, 0), 'grid'),
]
result = {'cases': {}}
if ONLY and (out / 'report.json').is_file():
    result = json.loads((out / 'report.json').read_text())
    result.pop('error', None)


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    from moonray_modo import host, rdla
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', SIZE), ('resY', SIZE), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    camera = scene.renderCamera
    camera.position.set((0, 0, 0))
    camera.channel('projType').set('persp')
    for channel_name, value in (('focalLen', .018), ('apertureX', .036), ('apertureY', .036)):
        camera.channel(channel_name).set(value)
    # A small cube far below: MoonRay draws no environment in a scene with no geometry.
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    for attribute, value in (('sizeX', .01), ('sizeY', .01), ('sizeZ', .01), ('cenY', -50.0)):
        lx.eval('tool.attr prim.cube %s %s' % (attribute, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    sun = next(iter(scene.items('sunLight')))
    environment = next(iter(scene.items('environment')))
    material = next(i for i in environment.children() if i.type == 'envMaterial')
    material.channel('type').set('physical')
    layers = {}

    def layer_for(kind):
        if kind in layers:
            return layers[kind]
        lx.eval('item.create %s' % ('imageMap' if kind == 'image' else kind))
        layer = scene.selected[0]
        lx.eval('texture.parent {%s} %d item:{%s}' % (environment.id, len(environment.children()), layer.id))
        if kind == 'image':
            lx.eval('clip.addStill {%s}' % str(out / 'uv_code.exr'))
            lx.eval('select.item {%s} set' % layer.id)
            lx.eval('texture.setIMap {%s}' % scene.items('videoStill')[-1].id)
        layer.channel('effect').set('envColor')
        layer.channel('opacity').set(.5)
        locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
        if kind == 'grid':
            locator.channel('projType').set('planar')
            locator.scale.set((.25, .25, .25))
            for channel_name, value in (('type', 'square'), ('lineWidth', .2), ('transWidth', .3)):
                layer.channel(channel_name).set(value)
        else:
            locator.channel('projType').set('spherical')
        layers[kind] = layer
        return layer

    for name, rotation, kind in CASES:
        if ONLY and name not in ONLY:
            continue
        entry = {}
        try:
            for other_kind, other in layers.items():
                other.channel('enable').set(other_kind == kind)
            if kind:
                layer_for(kind).channel('enable').set(True)
            sun.rotation.set(rotation, degrees=True)
            entry['sun_matrix'] = host.world_matrix(sun)
            for index, view in enumerate(VIEWS):
                label = '%s_v%d' % (name, index)
                camera.rotation.set(view, degrees=True)
                lx.eval('!render.animation {%s} openexr' % str(out / ('modo_%s' % label)))
                snapshot = host.snapshot()
                (out / ('%s.rdla' % label)).write_text(rdla.scene_text(snapshot, SIZE, SIZE, 4, 0.0, str(out / ('moonray_%s.exr' % label))), encoding='utf-8')
                kept = {k: v for k, v in snapshot.items() if not k.startswith('_')}
                (out / ('%s.json' % label)).write_text(json.dumps(kept, default=str), encoding='utf-8')
            entry['views'] = len(VIEWS)
            environments = snapshot.get('environments') or []
            entry['environment_kind'] = environments[0]['kind'] if environments else None
            entry['layers'] = [layer.get('kind') for layer in (environments[0].get('layers') or [])] if environments else []
            entry['warnings'] = [w for w in snapshot.get('warnings', []) if 'nvironment' in w or 'sky' in w or 'sun' in w.lower()][:6]
        except Exception:
            entry['error'] = traceback.format_exc()[-2500:]
        result['cases'][name] = entry
        save()
except Exception:
    result['error'] = traceback.format_exc()
save()
