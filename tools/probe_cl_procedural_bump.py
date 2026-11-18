# python
"""Command-line test: procedural bumps (Modo's Noise and Checker, Solid as Modo makes them) as Modo renders them and as
the plugin exports them. Four cubes in a row, lit from the side, each with a material of its own (by a material tag on
all its polygons) and, above it in the same group, a procedural layer set to Bump:
- Noise: one polygon a side;
- Checker: one polygon a side;
- Noise fine: 48 polygons along each edge;
- Noise, no UVs: one polygon a side, its UV map taken away.
Writes test-results/procedural-bump: bump.lxo, modo.*.exr (Modo's render), bump.rdla (the plugin's export, for
tools/check_procedural_bump.py) and report.json (what was built, each layer's projection and the plugin's notices)."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\procedural-bump')
out.mkdir(parents=True, exist_ok=True)
for old in out.glob('*'):
    old.unlink()
report = {'steps': [], 'layers': {}}
CUBES = (('Noise', 'noise', 1, True), ('Checker', 'checker', 1, True), ('NoiseFine', 'noise', 48, True), ('NoiseNoUV', 'noise', 1, False))
SPACING = 2.4


def step(name, command):
    report['steps'].append([name, 'started'])
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
    try:
        lx.eval(command)
        report['steps'][-1][1] = 'ok'
        return True
    except Exception as exc:
        report['steps'][-1][1] = 'failed: %s' % exc
        return False


def cube(name, x, segments):
    lx.eval('item.create mesh')
    mesh = modo.Scene().selected[-1]
    mesh.name = name
    lx.eval('tool.set prim.cube on')
    for attribute, value in (('cenX', x), ('cenY', 0), ('cenZ', 0), ('sizeX', 1.6), ('sizeY', 1.6), ('sizeZ', 1.6),
                             ('segmentsX', segments), ('segmentsY', segments), ('segmentsZ', segments), ('radius', 0)):
        try:
            lx.eval('tool.attr prim.cube %s %s' % (attribute, value))
        except Exception:
            pass
    lx.eval('tool.apply')
    lx.eval('tool.set prim.cube off')
    return mesh


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    render = scene.renderItem
    for name, value in (('resX', 1200), ('resY', 300), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    camera = scene.renderCamera
    modo.LocatorSuperType(camera).position.set((0, 0, 16))
    modo.LocatorSuperType(camera).rotation.set((0, 0, 0))
    camera.channel('focalLen').set(0.05)
    light = next(iter(scene.items('sunLight', superType=False)), None) or scene.addItem('sunLight')
    modo.LocatorSuperType(light).rotation.set((0, 1.2, 0))
    start = -SPACING * (len(CUBES) - 1) / 2
    for index, (name, kind, segments, uvs) in enumerate(CUBES):
        mesh = cube(name, start + SPACING * index, segments)
        lx.eval('select.typeFrom item')
        lx.eval('select.item {%s} set' % mesh.id)
        if not uvs:
            for vmap in list(mesh.geometry.vmaps.uvMaps):
                step(name + ': select UV map', 'select.vertexMap {%s} txuv replace' % vmap.name)
                step(name + ': delete UV map', 'vertMap.delete txuv')
            report.setdefault('uv maps left', {})[name] = [v.name for v in mesh.geometry.vmaps.uvMaps]
        lx.eval('select.typeFrom polygon')
        lx.eval('select.all')
        step(name + ': material', 'poly.setMaterial {%s}' % name)
        lx.eval('select.typeFrom item')
        mask = next(m for m in scene.items('mask', superType=False) if m.channel('ptag').get() == name)
        material = next(c for c in mask.children() if c.type == 'advancedMaterial')
        material.channel('diffCol').set((.6, .6, .6))
        material.channel('bumpAmp').set(0.05)
        lx.eval('select.item {%s} set' % mask.id)
        before = {m.id for m in scene.items(kind, superType=False)}
        step(name + ': add ' + kind, 'shader.create ' + kind)
        layer = next((m for m in scene.items(kind, superType=False) if m.id not in before), None)
        if layer is None:
            continue
        layer.channel('effect').set('bump')
        locator = next((i for i in layer.itemGraph('shadeLoc').forward() if i.type == 'txtrLocator'), None)
        if locator is not None and kind == 'checker':
            # A checker's height steps at its squares' edges, so its bump is lines along them: squares a quarter the
            # size, for several edges to cross the face. A texture locator's Size is its scale.
            try:
                modo.LocatorSuperType(locator).scale.set((.25, .25, .25))
            except Exception as exc:
                report['size'] = str(exc)
        report['layers'][name] = {'projection': locator.channel('projType').get() if locator else None,
                                  'parent': layer.parent.name, 'order': [c.name for c in mask.children()]}
    lx.eval('!scene.saveAs {%s} $LXOB false' % (out / 'bump.lxo'))
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo'))
    from moonray_modo import scene_export
    warnings = []
    scene_export.export({'path': out / 'bump.rdla', 'format': 'rdla', 'outputs': False, 'collect': False, 'frames': False}, warnings)
    report['warnings'] = warnings
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
