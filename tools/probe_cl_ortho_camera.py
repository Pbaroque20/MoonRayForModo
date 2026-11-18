# python
"""Command-line test: a Modo orthographic camera framed as Modo renders it and as the plugin exports it. Three marker
cubes face the camera: red at the middle, green to the right, blue above, a quarter of the width the plugin expects
apart. The camera is set one way after another (VARIANTS) and each is rendered by Modo (modo_<name>.*.exr) and exported
as the plugin writes it (<name>.rdla) and saved (ortho_<name>.lxo), for tools/check_ortho_camera.py to find the markers in both. Writes
test-results/ortho-camera/report.json with what the plugin read of each camera."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\ortho-camera')
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('*'):
    old.unlink()
report = {'variants': {}}
# Camera channels (and render or camera resolutions) for each variant, over an orthographic camera's defaults.
VARIANTS = (
    ('plain', {}, {}),
    ('focal100', {'focalLen': 0.1}, {}),
    ('target5', {'target': 5.0}, {}),
    ('focus6', {'focusDist': 6.0}, {}),
    ('focus6target2', {'focusDist': 6.0, 'target': 2.0}, {}),
    ('offset', {'offsetX': 0.004, 'offsetY': 0.002}, {}),
    ('wide', {}, {'resX': 800, 'resY': 400}),
    ('override', {'resOverride': 1, 'resX': 1500, 'resY': 1500}, {'resX': 1920, 'resY': 1080}),
)


def cube(name, size):
    lx.eval('item.create mesh')
    mesh = modo.Scene().selected[-1]
    mesh.name = name
    lx.eval('tool.set prim.cube on')
    for attribute, value in (('cenX', 0), ('cenY', 0), ('cenZ', 0), ('sizeX', size), ('sizeY', size), ('sizeZ', size),
                             ('segmentsX', 1), ('segmentsY', 1), ('segmentsZ', 1), ('radius', 0)):
        try:
            lx.eval('tool.attr prim.cube %s %s' % (attribute, value))
        except Exception:
            pass
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    return mesh


def coloured(scene, mesh, colour):
    """A material of its own, by a material tag on all its polygons."""
    lx.eval('select.typeFrom item')
    lx.eval('select.item {%s} set' % mesh.id)
    lx.eval('select.typeFrom polygon')
    lx.eval('select.all')
    lx.eval('poly.setMaterial {%s}' % mesh.name)
    lx.eval('select.typeFrom item')
    mask = next(m for m in scene.items('mask', superType=False) if m.channel('ptag').get() == mesh.name)
    for child in mask.children():
        if child.type == 'advancedMaterial':
            child.channel('diffCol').set(colour)
            child.channel('lumiCol').set(colour)
            child.channel('radiance').set(1.0)


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    camera = scene.renderCamera
    modo.LocatorSuperType(camera).position.set((0, 0, 50))
    modo.LocatorSuperType(camera).rotation.set((0, 0, 0))
    markers = {name: cube(name, 1.0) for name in ('Red', 'Green', 'Blue')}
    for name, colour in (('Red', (1, 0, 0)), ('Green', (0, 1, 0)), ('Blue', (0, 0, 1))):
        coloured(scene, markers[name], colour)
    report['camera channels'] = {c.name: c.get() for c in camera.channels() if c.name in (
        'projType', 'focalLen', 'target', 'focusDist', 'apertureX', 'apertureY', 'offsetX', 'offsetY', 'filmFit', 'resOverride')}
    from moonray_modo import scene_export, host
    for name, on_camera, on_render in VARIANTS:
        for channel, value in (('resX', 400), ('resY', 400), ('first', 1), ('last', 1)):
            render.channel(channel).set(value)
        camera.channel('projType').set('ortho')
        for channel, value in (('focalLen', 0.05), ('target', report['camera channels'].get('target', 1.0)),
                               ('focusDist', report['camera channels'].get('focusDist', 4.0)), ('offsetX', 0.0),
                               ('offsetY', 0.0), ('resOverride', 0)):
            camera.channel(channel).set(value)
        for channel, value in on_camera.items():
            camera.channel(channel).set(value)
        for channel, value in on_render.items():
            render.channel(channel).set(value)
        snapshot = host.snapshot()
        width = float(snapshot['camera']['ortho_width'])
        step = width / 4
        size = step / 3
        for marker, (x, y) in (('Red', (0, 0)), ('Green', (step, 0)), ('Blue', (0, step))):
            item = modo.LocatorSuperType(markers[marker])
            item.position.set((x, y, 0))
            item.scale.set((size, size, size))
        report['variants'][name] = {'plugin width': width, 'step': step, 'film offset': snapshot['camera'].get('film_offset'),
                                    'pixel aspect': snapshot['camera'].get('pixel_aspect'),
                                    'size': [render.channel('resX').get(), render.channel('resY').get()],
                                    'camera': {c: camera.channel(c).get() for c in ('focalLen', 'target', 'focusDist', 'offsetX', 'offsetY', 'resOverride', 'resX', 'resY')}}
        (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
        lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + name)))
        warnings = []
        scene_export.export({'path': out / (name + '.rdla'), 'format': 'rdla', 'outputs': False, 'collect': False, 'frames': False}, warnings)
        report['variants'][name]['warnings'] = warnings
        # Each variant's scene of its own, for MoonLightIPR to render in a test Modo (tools/probe_gui_item_mask_kinds.py).
        lx.eval('!scene.saveAs {%s} $LXOB false' % (out / ('ortho_%s.lxo' % name)))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
