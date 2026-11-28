# python
"""Command line: a Modo light's Shader Tree image (an Image Map layer under the light, beside its Light Material), as
Modo's own renderer draws it, and the scene the kit writes for MoonRay. The image is tools/make_uv_code_image.py's (its
colour is where in it a pixel is), so the floor's colour, seen from straight above, reads as the image coordinate Modo
looks up for each point the light reaches.

Each case is a new scene: a white floor 12 units across, a camera 8 units above it looking straight down (a 5.76 unit
square of floor, x to the right, -z up the picture), one light, no environment. Writes to PROBE_OUT
(test-results/light-images by default): modo_<case>.exr (Modo's render), <case>.rdla (the kit's scene, rendering
moonray_<case>.exr), <case>.json (the snapshot), <case>.lxo, and report.json (the layer's and its locator's channels,
the warnings). PROBE_IMAGE: the image (uv_code.exr in the folder); PROBE_CASES: case names, comma separated; PROBE_MLS=1 also writes <case>.mls, the scene packed for MoonLightIPR."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a103a4d6c0dba3d86\test-results\light-images'))
out.mkdir(parents=True, exist_ok=True)
IMAGE = os.environ.get('PROBE_IMAGE', str(out / 'uv_code.exr'))
ONLY = [c for c in os.environ.get('PROBE_CASES', '').split(',') if c]
SIZE = 256
RENDER_MODO = os.environ.get('PROBE_MODO', '1') == '1'

# name: (light type, position, rotation degrees XYZ, light channels, layer channels, locator channels)
CASES = [
    ('spot', 'spotLight', (0, 3, 0), (-90, 0, 0), {'cone': 0.6, 'radiance': 3.0}, {}, {}),
    ('spot_turned', 'spotLight', (0.5, 3, 0.3), (-80, 20, 15), {'cone': 0.6, 'radiance': 3.0}, {}, {}),
    ('spot_wide', 'spotLight', (0, 2, 0), (-90, 0, 0), {'cone': 1.2, 'edge': 0.2, 'radiance': 3.0}, {}, {}),
    ('area', 'areaLight', (0, 0.05, 0), (-90, 0, 0), {'width': 2.0, 'height': 1.2, 'radiance': 3.0}, {}, {}),
    ('area_high', 'areaLight', (0, 1.0, 0), (-90, 0, 0), {'width': 2.0, 'height': 1.2, 'radiance': 3.0}, {}, {}),
    ('point', 'pointLight', (0, 1.5, 0), (0, 0, 0), {'radiance': 3.0}, {}, {}),
    ('sun', 'sunLight', (0, 3, 0), (-90, 0, 0), {'radiance': 3.0}, {}, {}),
    ('spot_planar', 'spotLight', (0, 3, 0), (-90, 0, 0), {'cone': 0.6, 'radiance': 3.0}, {}, {'projType': 'planar', 'projAxis': 1}),
    ('spot_planar_z', 'spotLight', (0, 3, 0), (-90, 0, 0), {'cone': 0.6, 'radiance': 3.0}, {}, {'projType': 'planar', 'projAxis': 2}),
    ('spot_uv', 'spotLight', (0, 3, 0), (-90, 0, 0), {'cone': 0.6, 'radiance': 3.0}, {}, {'projType': 'uv'}),
    ('spot_front', 'spotLight', (0, 3, 0), (-90, 0, 0), {'cone': 0.6, 'radiance': 3.0}, {}, {'projType': 'front'}),
    ('spot_spherical', 'spotLight', (0, 3, 0), (-90, 0, 0), {'cone': 0.6, 'radiance': 3.0}, {}, {'projType': 'spherical'}),
    ('spot_lightprobe', 'spotLight', (0, 3, 0), (-90, 0, 0), {'cone': 0.6, 'radiance': 3.0}, {}, {'projType': 'lightprobe'}),
    # Second round: how an area light's picture is laid, and whether a light with a size shows one.
    ('area_uv', 'areaLight', (0, 0.05, 0), (-90, 0, 0), {'width': 2.0, 'height': 1.2, 'radiance': 3.0}, {}, {'projType': 'uv'}),
    ('area_planar_z', 'areaLight', (0, 0.05, 0), (-90, 0, 0), {'width': 2.0, 'height': 1.2, 'radiance': 3.0}, {}, {'projType': 'planar', 'projAxis': 2}),
    ('area_planar_y', 'areaLight', (0, 0.05, 0), (-90, 0, 0), {'width': 2.0, 'height': 1.2, 'radiance': 3.0}, {}, {'projType': 'planar', 'projAxis': 1}),
    ('area_planar_small', 'areaLight', (0, 0.05, 0), (-90, 0, 0), {'width': 2.0, 'height': 1.2, 'radiance': 3.0}, {},
     {'projType': 'planar', 'projAxis': 1, 'scale': (0.5, 0.5, 0.5)}),
    ('area_none_small', 'areaLight', (0, 0.05, 0), (-90, 0, 0), {'width': 2.0, 'height': 1.2, 'radiance': 3.0}, {}, {'scale': (0.5, 0.5, 0.5)}),
    ('area_turned', 'areaLight', (0.3, 0.05, -0.2), (-90, 30, 0), {'width': 2.0, 'height': 1.2, 'radiance': 3.0}, {}, {}),
    ('area_wrap', 'areaLight', (0, 0.05, 0), (-90, 0, 0), {'width': 2.0, 'height': 1.2, 'radiance': 3.0}, {}, {'wrapU': 2.0, 'wrapV': 3.0}),
    ('area_ellipse', 'areaLight', (0, 0.05, 0), (-90, 0, 0), {'width': 2.0, 'height': 1.2, 'radiance': 3.0, 'shape': 'ellipse'}, {}, {}),
    ('spot_radius', 'spotLight', (0, 3, 0), (-90, 0, 0), {'cone': 0.6, 'radiance': 3.0, 'radius': 0.4}, {}, {}),
    ('point_radius', 'pointLight', (0, 1.0, 0), (0, 0, 0), {'radiance': 3.0, 'radius': 0.6}, {}, {}),
    ('sun_spread', 'sunLight', (0, 3, 0), (-90, 0, 0), {'radiance': 3.0, 'spread': 0.3}, {}, {}),
    # Third round: an area light with no picture (its brightness alone), the locator moved and turned, and a half-opaque
    # picture over a red light.
    ('area_plain', 'areaLight', (0, 0.05, 0), (-90, 0, 0), {'width': 2.0, 'height': 1.2, 'radiance': 3.0}, None, {}),
    ('area_planar_z_moved', 'areaLight', (0, 0.05, 0), (-90, 0, 0), {'width': 2.0, 'height': 1.2, 'radiance': 3.0}, {},
     {'projType': 'planar', 'projAxis': 2, 'pos': (0.25, 0.1, 0.0)}),
    ('area_planar_z_turned', 'areaLight', (0, 0.05, 0), (-90, 0, 0), {'width': 2.0, 'height': 1.2, 'radiance': 3.0}, {},
     {'projType': 'planar', 'projAxis': 2, 'rot': (0, 0, 30)}),
    ('point_half_red', 'pointLight', (0, 1.5, 0), (0, 0, 0), {'radiance': 3.0, 'lightCol': (1.0, 0.0, 0.0)}, {'opacity': 0.5}, {}),
]
# Names tried as the locator's projType, to find every projection Modo has (one a light may use).
PROJECTIONS = ('planar', 'cylindrical', 'spherical', 'cubic', 'box', 'front', 'uv', 'lightprobe', 'implicitUV', 'triplanar', 'none',
               'light', 'lightProj', 'lightProjection', 'spot', 'spotlight', 'projector', 'camera', 'image', 'decal', 'gobo', 'parametric')
result = {'cases': {}}
if ONLY and (out / 'report.json').is_file():
    result = json.loads((out / 'report.json').read_text())
    result.pop('error', None)


def step(text):
    with (out / 'steps.log').open('a') as log:
        log.write(text + '\n')


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def set_channel(item, name, value):
    try:
        item.channel(name).set(value)
    except Exception:
        lx.eval('item.channel {%s} {%s} item:{%s}' % (name, value, item.id))


def channels(item):
    held = {}
    for index in range(item._item.ChannelCount()):
        name = item._item.ChannelName(index)
        try:
            if item._item.ChannelType(index) not in (lx.symbol.i_TYPE_FLOAT, lx.symbol.i_TYPE_INTEGER, lx.symbol.i_TYPE_STRING):
                continue
        except Exception:
            continue
        try:
            value = item.channel(name).get()
        except Exception:
            continue
        if isinstance(value, (int, float, str)):
            held[name] = value
    return held


def floor_and_camera(scene):
    lx.eval('item.create mesh {Floor}')
    floor = scene.selected[0]
    lx.eval('tool.set prim.cube on')
    for attribute, value in (('sizeX', 12.0), ('sizeY', .02), ('sizeZ', 12.0), ('cenY', -.01), ('segmentsX', 1), ('segmentsY', 1), ('segmentsZ', 1)):
        lx.eval('tool.attr prim.cube %s %s' % (attribute, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    lx.eval('select.type polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {Floor} {1.0 1.0 1.0} 0.8 0.0 true false')
    lx.eval('select.drop polygon')
    lx.eval('select.type item')
    camera = scene.renderCamera
    camera.position.set((0, 8, 0))
    camera.rotation.set((-90, 0, 0), degrees=True)
    for name, value in (('focalLen', .05), ('apertureX', .036), ('apertureY', .036)):
        camera.channel(name).set(value)
    return floor


try:
    from moonray_modo import host, rdla
    for name, kind, position, rotation, light_channels, layer_channels, locator_channels in CASES:
        if ONLY and name not in ONLY:
            continue
        entry = {}
        try:
            step('')
            lx.eval('scene.new')
            scene = modo.Scene()
            render = scene.renderItem
            for channel_name, value in (('resX', SIZE), ('resY', SIZE), ('first', 1), ('last', 1)):
                render.channel(channel_name).set(value)
            lx.eval('time.range scene 0.0 0.0')
            for light in list(scene.items('light')):
                scene.removeItems(light)
            environment = next(iter(scene.items('environment')))
            material = next((i for i in environment.children() if i.type == 'envMaterial'), None)
            if material is not None:
                material.channel('type').set('constant')
                for axis in 'RGB':
                    material.channel('zenColor.' + axis).set(0.0)
            step('floor_and_camera(scene)')
            floor_and_camera(scene)
            lx.eval('item.create %s' % kind)
            light = scene.selected[0]
            light.position.set(position)
            light.rotation.set(rotation, degrees=True)
            for channel_name, value in light_channels.items():
                if channel_name == 'lightCol':
                    light_material = next(c for c in light.children() if c.type == 'lightMaterial')
                    for axis, part in zip('RGB', value):
                        light_material.channel('lightCol.' + axis).set(part)
                    continue
                set_channel(light, channel_name, value)
            if layer_channels is None:
                layer = locator = None
            else:
                step('lx.eval(clip.addStill {%s} % I')
                lx.eval('clip.addStill {%s}' % IMAGE)
                clip = scene.items('videoStill')[-1]
                step('')
                lx.eval('item.create imageMap')
                layer = scene.selected[0]
                entry['effect_created'] = str(layer.channel('effect').get())
                lx.eval('texture.parent {%s} %d item:{%s}' % (light.id, len(light.children()), layer.id))
                lx.eval('select.item {%s} set' % layer.id)
                step('lx.eval(texture.setIMap {%s} %')
                lx.eval('texture.setIMap {%s}' % clip.id)
                entry['effect_parented'] = str(layer.channel('effect').get())
                for channel_name, value in layer_channels.items():
                    set_channel(layer, channel_name, value)
                locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
                step('entry[locator_default] = chann')
                entry['locator_default'] = channels(locator)
            if locator is not None and 'projections' not in result:
                accepted = {}
                for candidate in PROJECTIONS:
                    try:
                        lx.eval('item.channel txtrLocator$projType {%s} item:{%s}' % (candidate, locator.id))
                        accepted[candidate] = str(locator.channel('projType').get())
                    except Exception as exc:
                        accepted[candidate] = 'refused: %s' % exc
                result['projections'] = accepted
                locator.channel('projType').set('none')
            for channel_name, value in locator_channels.items():
                if channel_name == 'scale':
                    locator.scale.set(value)
                elif channel_name == 'pos':
                    locator.position.set(value)
                elif channel_name == 'rot':
                    locator.rotation.set(value, degrees=True)
                else:
                    set_channel(locator, channel_name, value)
            entry['children'] = [(c.type, c.name) for c in light.children()]
            if locator is not None:
                entry['layer'] = channels(layer)
                entry['locator'] = channels(locator)
                entry['locator_parent'] = locator.parent.type if locator.parent is not None else None
                entry['locator_world'] = host.world_matrix(locator)
            entry['light'] = channels(light)
            entry['light_world'] = host.world_matrix(light)
            step('')
            lx.eval('!scene.saveAs {%s} $LXOB false' % (out / ('%s.lxo' % name)))
            step('if RENDER_MODO:')
            if RENDER_MODO:
                lx.eval('!render.animation {%s} openexr' % str(out / ('modo_%s' % name)))
            step('')
            with host.by_engine('moonray'):
                snapshot = host.snapshot()
            (out / ('%s.rdla' % name)).write_text(rdla.scene_text(snapshot, SIZE, SIZE, 8, 0.0, str(out / ('moonray_%s.exr' % name))), encoding='utf-8')
            kept = {k: v for k, v in snapshot.items() if not k.startswith('_')}
            (out / ('%s.json' % name)).write_text(json.dumps(kept, default=str), encoding='utf-8')
            if os.environ.get('PROBE_MLS') == '1':
                # The scene as MoonLightIPR is given it (tools/render_snapshot_moonlightipr.py sends it to a session).
                from moonray_modo import moonlightipr_scene
                with host.by_engine('moonlightipr'):
                    seen = host.snapshot()
                payload, _, entry['moonlightipr_warnings'] = moonlightipr_scene.pack(seen, SIZE, SIZE, 0.0, set(), 512, denoise=False)
                (out / ('%s.mls' % name)).write_bytes(payload)
            entry['lights'] = [{k: v for k, v in l.items() if k not in ('matrix', 'matrix_close')} for l in snapshot.get('lights', [])]
            entry['warnings'] = snapshot.get('warnings', [])
        except Exception:
            entry['error'] = traceback.format_exc()[-2500:]
        result['cases'][name] = entry
        save()
    try:
        lx.eval('!scene.close')
    except Exception:
        pass
except Exception:
    result['error'] = traceback.format_exc()
save()
