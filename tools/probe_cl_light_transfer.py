# python
"""Command line: Move Shader Tree Textures to MoonShine Graphs (moonray.material.moveShaderTreeTextures) on a scene of
lights with Shader Tree images, and a Photometric light: whether the lights render the same after the move (their
layers switched off and clips taken out, records kept), a second run changes nothing, and undo and redo work.

The scene: tools/probe_cl_light_images.py's floor and camera, an area light with a picture laid across it (Planar along
Z: the image itself), a second area light with one laid by Solid (one row, made by the kit), a Point light whose image
is one colour, and a Photometric light (tools/make_test_ies.py's asym.ies). Run with tools/launch_cl_steps.py:
  probe  moonray.material.moveShaderTreeTextures  probe  moonray.material.moveShaderTreeTextures  probe  app.undo  probe
  app.undo  probe  app.redo  app.redo  probe
Writes to PROBE_OUT (test-results/light-transfer): before.rdla, after.rdla, undone.rdla, redone.rdla (rendering
<name>.exr), before.json/after.json (the lights as the snapshot has them), report.json."""
import builtins
import json
import os
import pathlib
import traceback
import lx
import modo

root = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\.claude\worktrees\agent-a103a4d6c0dba3d86')
out = pathlib.Path(os.environ.get('PROBE_OUT', str(root / 'test-results' / 'light-transfer')))
out.mkdir(parents=True, exist_ok=True)
IMAGE = str(root / 'test-results' / 'light-images' / 'uv_code.exr')
IES = str(root / 'test-results' / 'ies-lights' / 'asym.ies')
SIZE = 256


def save(report):
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def state():
    from moonray_modo import properties
    scene = modo.Scene()
    stored = (properties.scene_settings().get('production') or {}).get('lights') or {}
    return {'clips': sorted(c.name for c in scene.items('videoStill')),
            'layers': {layer.name: bool(layer.channel('enable').get()) for layer in scene.items('imageMap')},
            'records': {light.name: [r.get('name') for r in (stored.get(light.id) or {}).get('shader_tree_images') or []]
                        for light in scene.items('light')}}


def export(name, report):
    from moonray_modo import host, rdla
    with host.by_engine('moonray'):
        snapshot = host.snapshot()
    (out / (name + '.rdla')).write_text(rdla.scene_text(snapshot, SIZE, SIZE, 8, 0.0, str(out / (name + '.exr'))), encoding='utf-8')
    lights = [{k: v for k, v in l.items() if k not in ('matrix', 'matrix_close')} for l in snapshot.get('lights', [])]
    (out / (name + '.json')).write_text(json.dumps({k: v for k, v in snapshot.items() if not k.startswith('_')}, default=str), encoding='utf-8')
    report[name + ' lights'] = lights
    report[name + ' warnings'] = snapshot.get('warnings')


def image_layer(scene, light, clip, projection=None):
    lx.eval('item.create imageMap')
    layer = scene.selected[0]
    lx.eval('texture.parent {%s} %d item:{%s}' % (light.id, len(light.children()), layer.id))
    lx.eval('select.item {%s} set' % layer.id)
    lx.eval('texture.setIMap {%s}' % clip.id)
    if projection:
        locator = next(i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator')
        for name, value in projection.items():
            lx.eval('item.channel txtrLocator$%s {%s} item:{%s}' % (name, value, locator.id))
    return layer


def build():
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', SIZE), ('resY', SIZE), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    for light in list(scene.items('light')):
        scene.removeItems(light)
    environment = next(iter(scene.items('environment')))
    material = next((i for i in environment.children() if i.type == 'envMaterial'), None)
    if material is not None:
        material.channel('type').set('constant')
        for axis in 'RGB':
            material.channel('zenColor.' + axis).set(0.0)
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
    lx.eval('clip.addStill {%s}' % IMAGE)
    clip = scene.items('videoStill')[-1]
    made = {}
    for name, kind, position, channels, projection in (
            ('Picture', 'areaLight', (-1.2, .05, -1.0), {'width': 1.6, 'height': 1.0, 'radiance': 3.0}, {'projType': 'planar', 'projAxis': 2}),
            ('Row', 'areaLight', (1.2, .05, -1.0), {'width': 1.6, 'height': 1.0, 'radiance': 3.0}, None),
            ('Tinted', 'pointLight', (1.2, 1.0, 1.4), {'radiance': 1.0}, None),
            ('Profile', 'photometryLight', (-1.2, 1.2, 1.4), {'radiance': 1.0, 'filename': IES}, None)):
        lx.eval('item.create %s' % kind)
        light = scene.selected[0]
        light.name = name
        light.position.set(position)
        light.rotation.set((-90, 0, 0), degrees=True)
        for channel, value in channels.items():
            lx.eval('item.channel {%s} {%s} item:{%s}' % (channel, value, light.id))
        if kind != 'photometryLight':
            made[name] = image_layer(scene, light, clip, projection)
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'lights.lxo'))


held = getattr(builtins, '_light_transfer_probe', None)
if held is None:
    held = builtins._light_transfer_probe = {'phase': 0, 'report': {}}
held['phase'] += 1
phase, report = held['phase'], held['report']
try:
    if phase == 1:
        build()
        held['initial'] = report['initial'] = state()
        export('before', report)
    elif phase == 2:
        from moonray_modo import shader_tree_scene
        report['first report'] = list(shader_tree_scene.LAST_REPORT)
        held['first'] = report['first'] = state()
        export('after', report)
    elif phase == 3:
        from moonray_modo import shader_tree_scene
        report['again report'] = list(shader_tree_scene.LAST_REPORT)
        report['again'] = state()
        report['again unchanged'] = report['again'] == held['first']
        export('again', report)
    elif phase in (4, 5):
        undone = state()
        report['undo %d' % (phase - 3)] = {'state': undone, 'as before the command': undone == held['initial'], 'as after the first run': undone == held['first']}
        if phase == 5:
            export('undone', report)
    elif phase == 6:
        redone = state()
        report['redo: as after the first run'] = redone == held['first']
        export('redone', report)
except Exception:
    report['error phase %d' % phase] = traceback.format_exc()
save(report)
