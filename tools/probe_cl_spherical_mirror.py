# python
"""Command line: which way round Modo's Spherical camera lays the scene out, against the plugin's scenes for MoonRay.
Coloured cubes at +X (red), -X (green), +Z (blue), -Z (yellow) and above (+Y, magenta, a little toward -Z and +X)
around the camera at the origin, under an environment image (PROBE_IMAGE, tools/make_uv_code_image.py's: its colour is
where in it a pixel is) on a spherical Texture Locator. For each case Modo's render (modo_<case>.exr, unless
PROBE_MODO_RENDER=0), the plugin's scene for MoonRay (<case>.rdla, rendering moonray_<case>.exr) and its reading
(<case>.json, for MoonLightIPR). Cases: the Spherical Map camera unturned, turned 90 degrees about Y, turned (20, 35, 0);
Spherical VR unturned and turned (20, 35, 0); a perspective camera looking -Z (perspective cameras stay as they were).
PROBE_CASES: a comma-separated list of cases (all by default). PROBE_MOTION=1: the camera turns about Y from 0 to 40 degrees
over frames 0 to 2, Motion Blur on, and frame 1 is rendered and read as a render reads it (animation.capture_frame), the
blurred cases (blur_sph, blur_vr, blur_persp) in place of the others. Writes PROBE_OUT/report.json. Run: tools/launch_cl_probe.py probe_cl_spherical_mirror.py --profile <profile>."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\spherical-mirror'))
out.mkdir(parents=True, exist_ok=True)
IMAGE = os.environ.get('PROBE_IMAGE', str(out / 'uv_code.exr'))
MODO_RENDER = os.environ.get('PROBE_MODO_RENDER', '1') == '1'
SIZE = (360, 180)
CUBES = (('PlusX', (4, 0, 0), (1, .05, .05)), ('MinusX', (-4, 0, 0), (.05, 1, .05)), ('PlusZ', (0, 0, 4), (.05, .05, 1)),
         ('MinusZ', (0, 0, -4), (1, 1, .05)), ('Up', (1.2, 4, -1.5), (1, .05, 1)))
# name: projection, camera rotation (degrees XYZ), picture size
CASES = (('sph_0', 'spherical', (0, 0, 0), SIZE), ('sph_y90', 'spherical', (0, 90, 0), SIZE),
         ('sph_turned', 'spherical', (20, 35, 0), SIZE), ('vr_0', 'sphericalvr', (0, 0, 0), SIZE),
         ('vr_turned', 'sphericalvr', (20, 35, 0), SIZE),
         ('persp_0', 'persp', (0, 0, 0), (160, 160)))
MOTION = os.environ.get('PROBE_MOTION') == '1'
if MOTION:
    CASES = (('blur_sph', 'spherical', None, SIZE), ('blur_vr', 'sphericalvr', None, SIZE), ('blur_persp', 'persp', None, (160, 160)))
ONLY = [c for c in os.environ.get('PROBE_CASES', '').split(',') if c]
result = {'cases': {}}


def plain(value):
    """Arrays of numbers as lists, the rest as text."""
    try:
        return list(value)
    except TypeError:
        return str(value)


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    from moonray_modo import host, rdla
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('first', 1), ('last', 1)):
        render.channel(name).set(value)
    camera = scene.renderCamera
    camera.position.set((0, 0, 0))
    for channel_name, value in (('focalLen', .018), ('apertureX', .036), ('apertureY', .036)):
        camera.channel(channel_name).set(value)
    for name, position, colour in CUBES:
        lx.eval('item.create mesh')
        mesh = scene.selected[0]
        mesh.name = name
        lx.eval('tool.set prim.cube on')
        for attribute, value in (('sizeX', 1.0), ('sizeY', 1.0), ('sizeZ', 1.0), ('cenX', position[0]), ('cenY', position[1]), ('cenZ', position[2])):
            lx.eval('tool.attr prim.cube %s %s' % (attribute, value))
        lx.eval('tool.apply')
        lx.eval('tool.set prim.cube off')
        lx.eval('select.type polygon')
        lx.eval('select.all')
        lx.eval('poly.setMaterial %s {%s %s %s} 0.8 0.0 true false' % ((name,) + colour))
        lx.eval('select.type item')
    environment = next(iter(scene.items('environment')))
    material = next((i for i in environment.children() if i.type == 'envMaterial'), None)
    if material is not None:
        material.channel('type').set('constant')
        for axis in 'RGB':
            material.channel('zenColor.' + axis).set(0.0)
    lx.eval('clip.addStill {%s}' % IMAGE)
    clip = scene.items('videoStill')[-1]
    lx.eval('item.create imageMap')
    layer = scene.selected[0]
    lx.eval('texture.parent {%s} %d item:{%s}' % (environment.id, len(environment.children()), layer.id))
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('texture.setIMap {%s}' % clip.id)
    layer.channel('effect').set('envColor')
    locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
    locator.channel('projType').set('spherical')
    try:
        locator.channel('projAxis').set(1)
    except Exception:
        lx.eval('item.channel projAxis 1 item:{%s}' % locator.id)
    if MOTION:
        # Turning 40 degrees about Y over frames 0 to 2, blurred over Modo's default shutter (half a frame).
        fps = float(scene.fps)
        camera.channel('motionBlur').set(1)
        result['blurLen'] = camera.channel('blurLen').get()
        for frame, degrees in ((0, 0.0), (2, 40.0)):
            camera.rotation.y.set(degrees * 3.141592653589793 / 180, time=frame / fps, key=True)
        result['rotation_at_frame_1'] = camera.rotation.y.get(time=1 / fps)
        try:
            render.channel('motionBlur').set(1)
        except Exception:
            pass
    for name, projection, rotation, size in CASES:
        if ONLY and name not in ONLY:
            continue
        entry = {}
        try:
            render.channel('resX').set(size[0])
            render.channel('resY').set(size[1])
            camera.channel('projType').set(projection)
            entry['projType'] = str(camera.channel('projType').get())
            if rotation is not None:
                camera.rotation.set(rotation, degrees=True)
            if MODO_RENDER:
                lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + name)))
            if MOTION:
                from moonray_modo import animation
                snapshot = animation.capture_frame(1 / fps, motion=True, fps=fps)
            else:
                snapshot = host.snapshot()
            (out / (name + '.rdla')).write_text(rdla.scene_text(snapshot, size[0], size[1], 16, 0.0, str(out / ('moonray_%s.exr' % name))),
                                                encoding='utf-8')
            kept = {k: v for k, v in snapshot.items() if not k.startswith('_')}
            (out / (name + '.json')).write_text(json.dumps(kept, default=plain), encoding='utf-8')
            entry['cameras'] = [{k: e.get(k) for k in ('class', 'matrix', 'matrix_close', 'parameters')} for e in snapshot.get('entities') or []
                                if str(e.get('class', '')).endswith('Camera')]
            entry['camera_matrix'] = host.world_matrix(camera)
            entry['warnings'] = snapshot.get('warnings')
        except Exception:
            entry['error'] = traceback.format_exc()[-2500:]
        result['cases'][name] = entry
        save()
except Exception:
    result['error'] = traceback.format_exc()
save()
