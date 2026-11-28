# python
"""Command line: Modo's Photometric lights (and an IES profile on other lights, if Modo has one) as Modo's own renderer
draws them, and the scene the kit writes for MoonRay. Each case is a new scene: a white floor 12 units across, a camera 8
units above looking straight down (a 5.76 unit square, x right, -z up the picture), one light, no environment. The IES
files are tools/make_test_ies.py's.

Writes to PROBE_OUT (test-results/ies-lights by default): modo_<case>.exr, <case>.rdla (rendering moonray_<case>.exr),
<case>.json, <case>.lxo and report.json (each light's channels, every light type's channels naming a file, warnings).
PROBE_CASES: case names, comma separated; PROBE_MLS=1 also writes <case>.mls, the scene packed for MoonLightIPR; PROBE_MODO=0 skips Modo's render."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a103a4d6c0dba3d86\test-results\ies-lights'))
out.mkdir(parents=True, exist_ok=True)
ONLY = [c for c in os.environ.get('PROBE_CASES', '').split(',') if c]
RENDER_MODO = os.environ.get('PROBE_MODO', '1') == '1'
SIZE = 256

# name: (light type, position, rotation degrees XYZ, channels; 'ies' names a file in the folder)
CASES = [
    # Modo's Photometric light shines its IES nadir (0 degrees) along its own -Z: turned -90 about X it points down.
    ('down', 'photometryLight', (0, 2, 0), (-90, 0, 0), {'ies': 'down.ies'}),
    ('asym', 'photometryLight', (0, 2, 0), (-90, 0, 0), {'ies': 'asym.ies'}),
    ('up', 'photometryLight', (0, 2, 0), (90, 0, 0), {'ies': 'up.ies'}),
    ('asym_turned', 'photometryLight', (0.3, 2, -0.2), (-90, 40, 0), {'ies': 'asym.ies'}),
    ('asym_tilted', 'photometryLight', (0, 2, 0), (-70, 0, 10), {'ies': 'asym.ies'}),
    ('asym_spun', 'photometryLight', (0, 2, 0), (-90, 0, 35), {'ies': 'asym.ies'}),
    ('quad', 'photometryLight', (0, 2, 0), (-90, 0, 0), {'ies': 'quad.ies'}),
    ('down_bright', 'photometryLight', (0, 2, 0), (-90, 0, 0), {'ies': 'down.ies', 'radiance': 2.0}),
    ('down_low', 'photometryLight', (0, 1, 0), (-90, 0, 0), {'ies': 'down.ies'}),
    ('side', 'photometryLight', (0, 2, 0), (0, 0, 0), {'ies': 'asym.ies'}),]
result = {'cases': {}}
if ONLY and (out / 'report.json').is_file():
    result = json.loads((out / 'report.json').read_text())
    result.pop('error', None)


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


try:
    from moonray_modo import host, rdla
    for name, kind, position, rotation, light_channels in CASES:
        if ONLY and name not in ONLY:
            continue
        entry = {}
        try:
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
            floor_and_camera(scene)
            lx.eval('item.create %s' % kind)
            light = scene.selected[0]
            entry['defaults'] = channels(light)
            light.position.set(position)
            light.rotation.set(rotation, degrees=True)
            for channel_name, value in light_channels.items():
                if channel_name == 'ies':
                    set_channel(light, 'filename', str(out / value))
                else:
                    set_channel(light, channel_name, value)
            entry['light'] = channels(light)
            entry['filename'] = str(light.channel('filename').get())
            entry['clips'] = sorted((c.type, c.name) for c in scene.items('mediaClip', superType=True)) if hasattr(scene, 'items') else None
            entry['light_world'] = host.world_matrix(light)
            entry['children'] = [(c.type, c.name) for c in light.children()]
            lx.eval('!scene.saveAs {%s} $LXOB false' % (out / ('%s.lxo' % name)))
            if RENDER_MODO:
                lx.eval('!render.animation {%s} openexr' % str(out / ('modo_%s' % name)))
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
    if 'file_channels' not in result:
        # Every light type, and whether it has a channel naming a file (an IES profile on lights other than Photometric).
        found = {}
        lx.eval('scene.new')
        scene = modo.Scene()
        for kind in ('spotLight', 'pointLight', 'areaLight', 'sunLight', 'cylinderLight', 'domeLight', 'photometryLight', 'meshLight'):
            try:
                lx.eval('item.create %s' % kind)
                item = scene.selected[0]
                held = channels(item)
                found[kind] = {k: v for k, v in held.items() if isinstance(v, str) and ('file' in k.lower() or 'ies' in k.lower() or 'web' in k.lower())}
                found[kind]['_names'] = sorted(held)
            except Exception as exc:
                found[kind] = 'error: %s' % exc
        result['file_channels'] = found
    try:
        lx.eval('!scene.close')
    except Exception:
        pass
except Exception:
    result['error'] = traceback.format_exc()
save()
