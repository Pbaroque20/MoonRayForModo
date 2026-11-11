# python
"""Modo's Process texture's Bias and Gain as whole curves: a slab whose glow runs from 0 to 1 across it (a weight map
through a Vertex Map Texture on luminous colour), under a Process layer, rendered by Modo for each case; the
picture's middle row is the curve. Cases: Bias and Gain at 0.2, 0.3, 0.7, 0.8 alone, and two together; and an orange ramp
(black to orange) under Bias 0.3, to see whether the curve is per channel. Writes test-results/process-curves/."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\process-curves')
out.mkdir(parents=True, exist_ok=True)
CASES = {'plain': {}, 'bias20': {'bias': .2}, 'bias30': {'bias': .3}, 'bias70': {'bias': .7}, 'bias80': {'bias': .8},
         'gain20': {'gain': .2}, 'gain30': {'gain': .3}, 'gain70': {'gain': .7}, 'gain80': {'gain': .8},
         'bias30gain70': {'bias': .3, 'gain': .7}, 'bias70gain30': {'bias': .7, 'gain': .3}}
report = {'cases': {}}
try:
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Slab')
    geometry = modo.Mesh(mesh).geometry
    columns = 129
    points = [geometry.vertices.new((-1 + 2 * i / (columns - 1), y, 0)) for i in range(columns) for y in (-.5, .5)]
    for i in range(columns - 1):
        geometry.polygons.new((points[2 * i], points[2 * i + 2], points[2 * i + 3], points[2 * i + 1]))
    geometry.setMeshEdits()
    weights = geometry.vmaps.addWeightMap('Ramp')
    for vertex in geometry.vertices:
        weights[vertex.index] = (vertex.position[0] + 1) / 2
    geometry.setMeshEdits()
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('diffAmt').set(0)
    material.channel('specAmt').set(0)
    material.channel('radiance').set(1)
    scene.select(material)
    lx.eval('shader.create vmapTexture')
    ramp = next(i for i in scene.items('vmapTexture'))
    ramp.channel('effect').set('lumiColor')
    ramp.channel('vmap').set('Ramp')
    scene.select(ramp)
    lx.eval('shader.create process')
    process = next(i for i in scene.items('process'))
    process.channel('effect').set('lumiColor')
    camera = next(i for i in scene.items('camera'))
    modo.LocatorSuperType(camera).position.set((0, 0, 2.5))
    modo.LocatorSuperType(camera).rotation.set((0, 0, 0))
    camera.channel('projType').set('ortho') if 'projType' in [camera.internalItem.ChannelName(i) for i in range(camera.internalItem.ChannelCount())] else None
    render = scene.renderItem
    for name, value in (('resX', 256), ('resY', 32), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    for case, values in CASES.items():
        process.channel('bias').set(values.get('bias', .5))
        process.channel('gain').set(values.get('gain', .5))
        lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + case)))
        report['cases'][case] = values
        (out / 'report.json').write_text(json.dumps(report, indent=1))
    # An orange ramp under Bias 0.3: is the curve each channel's?
    for axis, part in zip('RGB', (0.8, 0.3, 0.1)):
        ramp.channel('color2.' + axis).set(part)
    process.channel('bias').set(.3)
    process.channel('gain').set(.5)
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo_orange_bias30'))
    process.channel('bias').set(.5)
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo_orange_plain'))
    report['rendered'] = sorted(p.name for p in out.glob('modo_*'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
