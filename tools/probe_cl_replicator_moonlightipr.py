# python
"""Command-line test: a replicator in MoonLightIPR. A cube is replicated over three points; the prototype is linked to
the replicator several ways until Modo's render cache shows the copies. The scene is then captured as the preview
captures it (still, and at the shutter's two ends for motion blur), and packed for MoonLightIPR: how many meshes and
placements each capture holds, and what packing says or refuses. Written to test-results/replicator-moonlightipr."""
import json
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\replicator-moonlightipr')
out.mkdir(parents=True, exist_ok=True)
result = {'tries': []}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def summary(snapshot):
    meshes = snapshot.get('meshes', [])
    return {'meshes': len(meshes), 'placements': sum(len(m.get('instances') or [1]) for m in meshes),
            'names': sorted({str(m.get('name')) for m in meshes}), 'extra': len(snapshot.get('extra_geometry') or []),
            'warnings': [w for w in snapshot.get('warnings', []) if 'renderOutput' not in w][:6],
            'instances_close': [len(m.get('instances_close') or []) for m in meshes if 'instances' in m]}


def pack(snapshot, label):
    from moonray_modo import moonlightipr_scene
    try:
        payload, keys, warnings = moonlightipr_scene.pack(snapshot, 320, 180, 0.15, (), 16, False, None)
        result[label + ' pack'] = {'bytes': len(payload), 'warnings': warnings[:6]}
    except Exception:
        result[label + ' pack'] = {'error': traceback.format_exc()[-1500:]}


try:
    lx.eval('scene.new')
    scene = modo.Scene()
    cube = scene.addMesh('Proto')
    corners = [(a - .25, b - .25, c - .25) for a in (0, .5) for b in (0, .5) for c in (0, .5)]
    with cube.geometry as geometry:
        points = [geometry.vertices.new(p) for p in corners]
        for face in ((0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)):
            geometry.polygons.new([points[i] for i in face])
    cloud = scene.addMesh('Points')
    with cloud.geometry as geometry:
        for p in ((-1.5, 0, 0), (0, 0, 0), (1.5, 0, 0)):
            geometry.vertices.new(p)
    replicator = scene.addItem('replicator', name='Copies')
    lx.eval('select.item {%s} set' % replicator.id)
    lx.eval('replicator.source {%s}' % cloud.id)
    graphs = ('particle', 'source', 'prototype', 'replicate', 'meshInst', 'groups')

    def links():
        found = {}
        for graph in graphs:
            try:
                g = replicator.itemGraph(graph)
                found[graph] = {'forward': [i.name for i in g.forward()], 'reverse': [i.name for i in g.reverse()]}
            except Exception as exc:
                found[graph] = str(exc)[:80]
        return found
    result['links after source'] = links()

    from moonray_modo import evaluated

    def copies():
        data = evaluated.capture(lx.service.Selection().GetTime())
        return sum(1 for s in data.get('surfaces', []) if 'Proto' in str(s.get('source_item')) or s.get('instanced'))

    def link(graph, a, b):
        a.itemGraph(graph) >> b.itemGraph(graph)

    tries = [('item.link particle prototype->replicator', lambda: lx.eval('item.link particle {%s} {%s}' % (cube.id, replicator.id))),
             ('item.link particle replicator->prototype', lambda: lx.eval('item.link particle {%s} {%s}' % (replicator.id, cube.id))),
             ('graph particle prototype->replicator', lambda: link('particle', cube, replicator)),
             ('graph particle replicator->prototype', lambda: link('particle', replicator, cube)),
             ('graph source prototype->replicator', lambda: link('source', cube, replicator)),
             ('graph source replicator->prototype', lambda: link('source', replicator, cube))]
    for name, attempt in tries:
        try:
            attempt()
            outcome = 'ran'
        except Exception as exc:
            outcome = 'failed: %s' % str(exc)[:120]
        try:
            found = copies()
        except Exception as exc:
            found = 'capture failed: %s' % str(exc)[:200]
        result['tries'].append([name, outcome, found])
        save()
        if isinstance(found, int) and found >= 3:
            result['linked by'] = name
            break
    result['links'] = links()
    from moonray_modo import host
    still = host.snapshot()
    result['still'] = summary(still)
    pack(still, 'still')
    from moonray_modo.animation import capture_frame
    try:
        moving = capture_frame(lx.service.Selection().GetTime(), True, True, float(scene.fps))
        result['motion'] = summary(moving)
        pack(moving, 'motion')
    except Exception:
        result['motion'] = {'error': traceback.format_exc()[-1500:]}
except Exception:
    result['error'] = traceback.format_exc()
save()
