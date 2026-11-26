# python
"""Command line: which way Modo shows and turns a spherical HDRI, through a perspective camera, against the plugin's
scenes for MoonRay. A compass HDRI (PROBE_HDRI; -Z red, +X green, +Z yellow, -X blue in the layout the kit takes for
Modo's) on an environment image layer (spherical Texture Locator), turned by 0 and 90 degrees (Rotation Y), seen by a
90-degree perspective camera at the origin looking -Z, -X, +Z and +X. For each: Modo's render (modo_<turn>_<view>.exr)
and the plugin's scene for MoonRay (<turn>_<view>.rdla). Then the same HDRI on a Backplate item (Hdri Rotation 0 and 90,
seen by the camera) in place of the layer: bp_<turn>_<view>.rdla. Writes PROBE_OUT/report.json.
Run: tools/launch_cl_probe.py probe_cl_hdri_compass.py --timeout 900."""
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\hdri-compass'))
out.mkdir(parents=True, exist_ok=True)
HDRI = os.environ['PROBE_HDRI']
SIZE = (96, 96)
VIEWS = (('mZ', (0, 0, 0)), ('mX', (0, 90, 0)), ('pZ', (0, 180, 0)), ('pX', (0, 270, 0)))
TURNS = (0, 90)
MODO_RENDER = os.environ.get('PROBE_MODO_RENDER', '1') == '1'
result = {'cases': {}}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    from moonray_modo import host, rdla, entities
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', SIZE[0]), ('resY', SIZE[1]), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    for light in scene.items('sunLight'):
        light.channel('render').set('off')
    camera = scene.renderCamera
    camera.position.set((0, 0, 0))
    camera.channel('projType').set('persp')
    for channel_name, value in (('focalLen', .018), ('apertureX', .036), ('apertureY', .036)):
        camera.channel(channel_name).set(value)
    lx.eval('item.create mesh')
    lx.eval('tool.set prim.cube on')
    for attribute, value in (('sizeX', .01), ('sizeY', .01), ('sizeZ', .01), ('cenY', -50.0)):
        lx.eval('tool.attr prim.cube %s %s' % (attribute, value))
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    environment = next(iter(scene.items('environment')))
    material = next((i for i in environment.children() if i.type == 'envMaterial'), None)
    if material is not None:
        material.channel('type').set('constant')
        for axis in 'RGB':
            material.channel('zenColor.' + axis).set(0.0)
    lx.eval('clip.addStill {%s}' % HDRI)
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
    result['projAxis'] = str(locator.channel('projAxis').get())
    for turn in TURNS:
        locator.rotation.set((0, turn, 0), degrees=True)
        for label, view in VIEWS:
            name = '%d_%s' % (turn, label)
            camera.rotation.set(view, degrees=True)
            if MODO_RENDER:
                lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + name)))
            snapshot = host.snapshot()
            (out / (name + '.rdla')).write_text(rdla.scene_text(snapshot, SIZE[0], SIZE[1], 4, 0.0, str(out / ('moonray_%s.exr' % name))),
                                                encoding='utf-8')
            result['cases'][name] = {'matrix': host.world_matrix(locator),
                                     'environments': [{k: e.get(k) for k in ('kind', 'matrix', 'path')} for e in snapshot.get('environments') or []]}
            save()
    # The Backplate in place of the layer.
    layer.channel('enable').set(False)
    lx.eval('moonray.entity.add BackplateEnvironment')
    plate = [i for i in scene.items() if i.type == entities.item_type('BackplateEnvironment')][0]
    lx.eval('select.item {%s} set' % plate.id)
    kind = entities.item_type('BackplateEnvironment')
    lx.eval('item.channel %s$%shdri {%s}' % (kind, entities.CHANNEL_PREFIX, HDRI))
    lx.eval('item.channel %s$%shdri_camera true' % (kind, entities.CHANNEL_PREFIX))
    lx.eval('item.channel %s$%sground false' % (kind, entities.CHANNEL_PREFIX))
    for turn in TURNS:
        lx.eval('select.item {%s} set' % plate.id)
        lx.eval('item.channel %s$%shdri_rotation %s' % (kind, entities.CHANNEL_PREFIX, turn))
        for label, view in VIEWS:
            name = 'bp_%d_%s' % (turn, label)
            camera.rotation.set(view, degrees=True)
            snapshot = host.snapshot()
            (out / (name + '.rdla')).write_text(rdla.scene_text(snapshot, SIZE[0], SIZE[1], 4, 0.0, str(out / ('moonray_%s.exr' % name))),
                                                encoding='utf-8')
            result['cases'][name] = {'environments': [{k: e.get(k) for k in ('kind', 'matrix', 'path', 'name')} for e in snapshot.get('environments') or []],
                                     'warnings': snapshot.get('warnings')}
            save()
except Exception:
    result['error'] = traceback.format_exc()
save()
