# python
"""Command line: replicator copies paired by particle ID through the shutter. A cube replicated over a particle
simulation (a radial emitter, particles killed young), so that copies are born and die during the shutter and Modo
renumbers them. At the shutter's ends and the frame (Modo's time set there, as animation.capture_frame reads them):
what Modo's replicator enumerator says of each copy (its particle ID, position) beside the render cache's surfaces
(instance_index, position, and the particle_id evaluated.particle_ids gave). Then the scene as the kit captures it with
motion blur: each copy's open and close positions against where the enumerator puts that particle at the ends.
Writes PROBE_OUT/report.json (test-results/replicator/particle-ids).

PROBE_RATE (particles a second, 60), PROBE_AGE (seconds a particle lives, 0.3), PROBE_FRAME (30)."""
import json
import math
import os
import pathlib
import traceback
import lx
import lxifc
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\replicator\particle-ids'))
out.mkdir(parents=True, exist_ok=True)
report = {}
FRAME = float(os.environ.get('PROBE_FRAME', '30'))
SPEED = 2.0


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


class Visitor(lxifc.Visitor):
    def __init__(self, enumerator):
        self.enumerator = enumerator
        self.rows = []

    def vis_Evaluate(self):
        e = self.enumerator
        self.rows.append({'id': '%.9g' % e.Id(), 'pos': list(e.Position())})


def enumerate_copies(replicator, time):
    enumerator = lx.object.ReplicatorEnumerator(lx.service.Particle().GetReplicatorEnumerator(lx.object.Item(replicator)))
    raw = lx.object.Scene(lx.object.Item(replicator).Context())
    visitor = Visitor(enumerator)
    enumerator.Enumerate(visitor, lx.object.ChannelRead(raw.Channels(None, time)), 0)
    return visitor.rows


try:
    from moonray_modo import evaluated, animation
    lx.eval('scene.new')
    scene = modo.Scene()
    cube = scene.addMesh('Proto')
    with cube.geometry as geo:
        c = [geo.vertices.new((a - .05, b - .05, d - .05)) for a in (0, .1) for b in (0, .1) for d in (0, .1)]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geo.polygons.new([c[i] for i in face])
    lx.eval('item.create radialEmitter')
    emitter = next(i for i in scene.items('radialEmitter'))
    sim = next(i for i in scene.items('particleSim'))
    emitter.channel('rate').set(float(os.environ.get('PROBE_RATE', '60')))
    emitter.channel('velocity').set(SPEED)
    emitter.channel('velocitySpread').set(0.0)
    sim.channel('ageKill').set(True)
    sim.channel('ageMax').set(float(os.environ.get('PROBE_AGE', '0.3')))
    sim.channel('gravEnable').set(False)
    # A replicator over a mesh's points, made first: its copies keep their places (no IDs asked of a mesh), and Modo
    # numbers the particle replicator's copies of the same prototype on from them.
    cloud = scene.addMesh('Points')
    with cloud.geometry as geo:
        for x in range(3):
            geo.vertices.new((float(x), 5.0, 0.0))
    still = scene.addItem('replicator', name='MeshCopies')
    lx.eval('select.item {%s} set' % still.id)
    lx.eval('replicator.source {%s}' % cube.id)
    cloud.itemGraph('particle') >> still.itemGraph('particle')
    replicator = scene.addItem('replicator', name='Copies')
    # replicator.source names the prototype (a particle link from the replicator to it); the point source is linked
    # to the replicator by the particle graph.
    lx.eval('select.item {%s} set' % replicator.id)
    lx.eval('replicator.source {%s}' % cube.id)
    sim.itemGraph('particle') >> replicator.itemGraph('particle')
    fps = lx.eval('time.fpsCustom ?') or 24.0
    time = FRAME / fps
    # The simulation run, as Modo's Simulate button does (without its dialog).
    lx.eval('!simulate start:0 end:%g' % (FRAME + 10))
    lx.eval('select.time %g' % time)
    report['fps'] = fps
    half = 0.25 / fps  # the default shutter: half a frame about the frame
    truth, order = {}, {}
    report['moments'] = {}
    for label, moment in (('open', time - half), ('frame', time), ('close', time + half)):
        lx.service.Selection().SetTime(moment)
        rows = enumerate_copies(replicator, moment)
        truth[label] = {row['id']: row['pos'] for row in rows}
        order[label] = [row['id'] for row in rows]
        surfaces = [s for s in evaluated.capture(moment)['surfaces'] if s.get('instanced') and s['source_item'] == replicator.id]
        first = min([s['instance_index'] for s in surfaces] or [0])
        by_index = {s['instance_index'] - first: s for s in surfaces}
        # The render cache's instance_index against the enumerator's order (one prototype here), and the particle_id
        # the kit gave each surface against the enumerator's ID for that place.
        placed = sum(1 for i, row in enumerate(rows) if i in by_index and math.dist(by_index[i]['matrix'][12:15], row['pos']) < 1e-3)
        named = sum(1 for i, row in enumerate(rows) if i in by_index and by_index[i].get('particle_id') == row['id'])
        report['moments'][label] = {'copies': len(rows), 'surfaces': len(surfaces), 'unique_ids': len(truth[label]),
                                    'first_index': first, 'index_order_agrees': placed, 'particle_id_agrees': named}
    lx.service.Selection().SetTime(time)
    report['particles'] = {'born in shutter': len(set(truth['close']) - set(truth['open'])),
                           'died in shutter': len(set(truth['open']) - set(truth['close'])),
                           # What the old pairing (by place) would have joined to another particle.
                           'paired to another particle by place': sum(1 for a, b in zip(order['open'], order['close']) if a != b)}
    save()
    # The kit's motion capture, as a render reads it and as MoonLightIPR's realtime preview does (evaluated).
    for mode, reading in (('render', False), ('realtime', True)):
        snapshot = animation.capture_frame(time, evaluated=reading, motion=True, fps=fps, preview=reading)
        report['mesh replicator ids ' + mode] = sorted({str(i) for m in snapshot.get('meshes', []) for i in m.get('instance_ids') or []
                                                         if str(i).startswith(still.id)})
        report.setdefault('motion', {})[mode] = {}
        for mesh in snapshot.get('meshes', []):
            if not any(str(i).startswith(replicator.id + '|') for i in mesh.get('instance_ids') or []):
                continue
            ids = mesh['instance_ids']
            opened, closed = mesh.get('instances') or [], mesh.get('instances_close') or []
            rows = []
            for identity, a, b in zip(ids, opened, closed):
                word = str(identity).split('|')[1]
                if not word.startswith('p'):
                    continue
                pid = word[1:]
                rows.append({'step': math.dist(a[12:15], b[12:15]),
                             # Where Modo has this particle at the shutter's ends; a copy not there at an end is held where
                             # it is at the frame for that end.
                             'open_off': math.dist(a[12:15], truth['open'][pid]) if pid in truth['open'] else None,
                             'close_off': math.dist(b[12:15], truth['close'][pid]) if pid in truth['close'] else None})
            expected = SPEED * 2 * half
            report['motion'][mode][mesh.get('identity')] = {
                'name': mesh.get('name'), 'copies': len(ids), 'by particle id': len(rows), 'first_ids': ids[:4],
                'expected_step': expected, 'longest_step': max([r['step'] for r in rows] or [0]),
                'held at an end': sum(1 for r in rows if r['open_off'] is None or r['close_off'] is None),
                'longer than 1.5x a particle step': sum(1 for r in rows if r['step'] > 1.5 * expected),
                'largest open error': max([r['open_off'] for r in rows if r['open_off'] is not None] or [0]),
                'largest close error': max([r['close_off'] for r in rows if r['close_off'] is not None] or [0])}
    report['warnings'] = [w for w in snapshot.get('warnings', []) if 'cop' in w.lower() or 'shutter' in w.lower()]
except Exception:
    report['error'] = traceback.format_exc()
save()
