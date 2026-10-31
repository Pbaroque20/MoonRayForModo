# python
"""Modo's Weight Map Texture layer against Modo's own render. A thin slab facing the camera whose weight runs from 0 to 1
across it, glowing by the layer alone, with default and with bent Low, High, Bias and Gain; Modo renders each, and the
scene as the plugin hands it to MoonRay is kept for rendering outside Modo. Writes test-results/weight-layer/<case>.pickle,
modo_<case>*.exr and report.json."""
import json
import pathlib
import pickle
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\weight-layer')
out.mkdir(parents=True, exist_ok=True)
CASES = {'plain': dict(value1=0.0, value2=1.0, bias=.5, gain=.5, color1=(0, 0, 0), color2=(1, 1, 1)),
         'bent': dict(value1=.2, value2=.8, bias=.3, gain=.7, color1=(.2, .2, .2), color2=(.8, .8, .8))}
report = {}
try:
    from moonray_modo import host
    lx.eval('scene.new')
    scene = modo.Scene()
    mesh = scene.addMesh('Slab')
    geometry = modo.Mesh(mesh).geometry
    columns = 65
    points = [geometry.vertices.new((-1 + 2 * i / (columns - 1), y, 0)) for i in range(columns) for y in (-.5, .5)]
    for i in range(columns - 1):
        geometry.polygons.new((points[2 * i], points[2 * i + 2], points[2 * i + 3], points[2 * i + 1]))
    geometry.setMeshEdits()
    weights = geometry.vmaps.addWeightMap('Cornea')
    for vertex in geometry.vertices:
        weights[vertex.index] = (vertex.position[0] + 1) / 2
    geometry.setMeshEdits()
    material = next(i for i in scene.items('advancedMaterial'))
    material.channel('diffAmt').set(0)
    material.channel('specAmt').set(0)
    material.channel('radiance').set(1)
    scene.select(material)
    lx.eval('shader.create vmapTexture')
    layer = next(i for i in scene.items('vmapTexture'))
    layer.channel('effect').set('lumiColor')
    layer.channel('vmap').set('Cornea')
    report['effect'] = layer.channel('effect').get()
    report['vmap'] = layer.channel('vmap').get()
    camera = next(i for i in scene.items('camera'))
    modo.LocatorSuperType(camera).position.set((0, 0, 3))
    modo.LocatorSuperType(camera).rotation.set((0, 0, 0))
    render = scene.renderItem
    for name, value in (('resX', 320), ('resY', 180), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    for case, values in CASES.items():
        for name, value in values.items():
            if name.startswith('color'):
                for axis, part in zip('RGB', value):
                    layer.channel(name + '.' + axis).set(part)
            else:
                layer.channel(name).set(value)
        snapshot = host.snapshot()
        report[case + ' warnings'] = snapshot.get('warnings')
        report[case + ' layers'] = [[l.get('kind'), l.get('effect'), (l.get('gradient') or {}).get('vmap')] for m in snapshot['materials'].values() for l in (m.get('layers') or [])]
        (out / (case + '.pickle')).write_bytes(pickle.dumps(snapshot, protocol=4))
        lx.eval('!render.animation {%s} openexr' % str(out / ('modo_' + case)))
    report['rendered'] = [p.name for p in out.glob('modo_*')]
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
