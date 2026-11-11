# python
"""Command-line: Modo's Variation Texture by Particle against Modo's own render: a cube replicated over five points in a row, glowing
by the layer (luminous colour, a ramp from 0 to 1, so that the glow is the replica's number). Modo renders it, and the
scene as the kit captures it is kept. Writes test-results/variation-particle/modo_particle.exr, particle.pickle and
report.json."""
import json
import pathlib
import pickle
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\variation-particle-cl')
out.mkdir(parents=True, exist_ok=True)
report = {}
try:
    from moonray_modo import host
    from moonray_modo.procedurals import VARIATION_PARTICLE_MAP
    lx.eval('scene.new')
    scene = modo.Scene()
    cube = scene.addMesh('Proto')
    with cube.geometry as geo:
        c = [geo.vertices.new((a - .3, b - .3, d - .3)) for a in (0, .6) for b in (0, .6) for d in (0, .6)]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geo.polygons.new([c[i] for i in face])
    cloud = scene.addMesh('Points')
    with cloud.geometry as geo:
        for x in (-2, -1, 0, 1, 2):
            geo.vertices.new((float(x), 0.0, 0.0))
    replicator = scene.addItem('replicator', name='Copies')
    lx.eval('select.item {%s} set' % replicator.id)
    lx.eval('replicator.source {%s}' % cloud.id)
    # As tools/probe_cl_replicator_moonlightipr.py found the copies made: these links in this order.
    for attempt in (lambda: lx.eval('item.link particle {%s} {%s}' % (cube.id, replicator.id)),
                    lambda: lx.eval('item.link particle {%s} {%s}' % (replicator.id, cube.id)),
                    lambda: cube.itemGraph('particle') >> replicator.itemGraph('particle'),
                    lambda: replicator.itemGraph('particle') >> cube.itemGraph('particle')):
        try:
            attempt()
        except Exception as exc:
            report.setdefault('link notes', []).append(str(exc)[:120])
    from moonray_modo import evaluated
    report['copies'] = sum(1 for s in evaluated.capture(lx.service.Selection().GetTime()).get('surfaces', [])
                           if 'Proto' in str(s.get('source_item')) or s.get('instanced'))
    material = next(i for i in scene.items('advancedMaterial'))
    for name, value in (('diffAmt', 0), ('specAmt', 0), ('radiance', 1)):
        material.channel(name).set(value)
    scene.select(material)
    lx.eval('shader.create variationTexture')
    layer = next(i for i in scene.items('variationTexture'))
    layer.channel('effect').set('lumiColor')
    layer.channel('type').set('particle')
    report['type'] = layer.channel('type').get()
    for axis in 'RGB':
        for x in (0.0, 1.0):
            lx.eval('channel.key time:%g value:%g channel:{%s:color.%s}' % (x, x, layer.id, axis))
    curve = lx.object.GradientFilter(layer.channel('color.R').get())
    report['curve'] = [[x / 100.0, curve.Generate(x / 100.0)] for x in range(101)]
    camera = next(i for i in scene.items('camera'))
    scene.select(camera)
    for name, value in (('pos.X', 0), ('pos.Y', 0), ('pos.Z', 8), ('rot.X', 0), ('rot.Y', 0), ('rot.Z', 0)):
        lx.eval('transform.channel %s %s' % (name, value))
    render = scene.renderItem
    for name, value in (('resX', 320), ('resY', 96), ('first', 1), ('last', 1)):
        render.channel(name).set(value)
    snapshot = host.snapshot()
    report['warnings'] = [w for w in snapshot.get('warnings', []) if 'ariation' in w or 'eplicator' in w]
    report['meshes'] = [{'name': m.get('name'), 'identity': m.get('identity'), 'placements': len(m.get('instances') or [1]),
                         'numbers': m.get('instance_variation'), 'instance_ids': m.get('instance_ids')} for m in snapshot['meshes']]
    report['map'] = VARIATION_PARTICLE_MAP
    (out / 'particle.pickle').write_bytes(pickle.dumps(snapshot, protocol=4))
    lx.eval('!render.animation {%s} openexr' % str(out / 'modo_particle'))
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
lx.eval('!app.quit')
