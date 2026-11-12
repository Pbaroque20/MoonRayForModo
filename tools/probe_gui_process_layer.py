# python
"""Modo's Process texture against Modo's own render, to translate it: a slab facing the camera that glows by its layers
alone, a Constant of a known colour under a Process layer (both on luminous colour). Modo renders each case small; the
colour in the middle of each picture is what the Process made of the colour beneath. Cases: three colours, and each of
Hue, Saturation, Value, Hue Shift, Bias and Gain moved alone, then together. Writes test-results/process-layer/
report.json and modo_<case>.exr."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\process-layer')
out.mkdir(parents=True, exist_ok=True)
COLOURS = {'orange': (0.8, 0.3, 0.1), 'blue': (0.2, 0.5, 0.9), 'grey': (0.5, 0.5, 0.5)}
SETTINGS = {'none': {}, 'hue25': {'hue': 0.25}, 'hue50': {'hue': 0.5}, 'sat-50': {'sat': -0.5}, 'sat+50': {'sat': 0.5},
            'val-50': {'val': -0.5}, 'val+50': {'val': 0.5}, 'shift25': {'hueShift': 0.25}, 'shift90deg': {'hueShift': 90.0},
            'bias30': {'bias': 0.3}, 'bias70': {'bias': 0.7}, 'gain30': {'gain': 0.3}, 'gain70': {'gain': 0.7},
            'mixed': {'hue': 0.1, 'sat': 0.3, 'val': -0.2, 'bias': 0.6, 'gain': 0.4}}
report = {'cases': {}}
try:
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Slab')
    geometry = modo.Mesh(mesh).geometry
    corners = [geometry.vertices.new(p) for p in ((-1, -.6, 0), (1, -.6, 0), (1, .6, 0), (-1, .6, 0))]
    geometry.polygons.new(corners)
    geometry.setMeshEdits()
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('diffAmt').set(0)
    material.channel('specAmt').set(0)
    material.channel('radiance').set(1)
    scene.select(material)
    lx.eval('shader.create constant')
    constant = next(i for i in scene.items('constant'))
    constant.channel('effect').set('lumiColor')
    scene.select(constant)
    lx.eval('shader.create process')
    process = next(i for i in scene.items('process'))
    process.channel('effect').set('lumiColor')
    report['order'] = [(c.name, c.type) for c in scene.renderItem.children()] + [(c.name, c.type) for c in material.parent.children()] if material.parent else []
    camera = next(i for i in scene.items('camera'))
    modo.LocatorSuperType(camera).position.set((0, 0, 3))
    modo.LocatorSuperType(camera).rotation.set((0, 0, 0))
    render = scene.renderItem
    for name, value in (('resX', 32), ('resY', 18), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    defaults = {k: process.channel(k).get() for k in ('hue', 'sat', 'val', 'hueShift', 'bias', 'gain')}
    report['defaults'] = defaults
    for colour_name, colour in COLOURS.items():
        for axis, part in zip('RGB', colour):
            constant.channel('color.' + axis).set(part)
        for setting_name, values in SETTINGS.items():
            for key, value in defaults.items():
                process.channel(key).set(values.get(key, value))
            case = colour_name + '_' + setting_name
            try:
                lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + case)))
                report['cases'][case] = {'colour': colour, 'settings': values}
            except Exception as exc:
                report['cases'][case] = {'error': str(exc)}
            (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
    report['rendered'] = sorted(p.name for p in out.glob('modo_*'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
