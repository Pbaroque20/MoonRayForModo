# python
"""Command-line test: the replicators of a saved scene (MOONRAY_PROBE_SCENE, opened and never saved) in MoonLightIPR.
For each replicator: what feeds it and what it copies, and how many copies Modo's render cache holds of each source;
then the scene captured as the preview captures it (still, and for motion blur) and packed for MoonLightIPR: how many
meshes and placements each holds, per source item, and what packing says or refuses.
Written to test-results/scene-replicators/report.json."""
import collections
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\scene-replicators')
out.mkdir(parents=True, exist_ok=True)
result = {}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def per_source(snapshot):
    counts = collections.Counter()
    for mesh in snapshot.get('meshes', []):
        source = mesh.get('source_item') or str(mesh.get('identity', '')).split('|')[0]
        counts[source] += len(mesh.get('instances') or [1])
    return dict(counts)


def summary(snapshot):
    meshes = snapshot.get('meshes', [])
    return {'meshes': len(meshes), 'placements': sum(len(m.get('instances') or [1]) for m in meshes),
            'by_source': per_source(snapshot), 'extra': collections.Counter(e.get('kind') for e in snapshot.get('extra_geometry') or []),
            'warnings': [w for w in snapshot.get('warnings', []) if 'renderOutput' not in w][:12]}


def pack(snapshot, label):
    from moonray_modo import moonlightipr_scene
    try:
        payload, keys, warnings = moonlightipr_scene.pack(snapshot, 320, 180, 0.15, (), 16, False, None)
        result[label + ' pack'] = {'bytes': len(payload), 'warnings': warnings[:12]}
    except Exception:
        result[label + ' pack'] = {'error': traceback.format_exc()[-2000:]}


try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    scene = modo.Scene()
    names = {item.id: item.name for item in scene.items()}
    result['replicators'] = []
    for replicator in scene.items('replicator', superType=False):
        entry = {'name': replicator.name, 'id': replicator.id, 'visible': replicator.channel('visible').get() if 'visible' in replicator.channelNames else None}
        for graph in ('particle', 'source', 'meshInst', 'groups'):
            try:
                g = replicator.itemGraph(graph)
                entry[graph] = {'forward': ['%s (%s)' % (i.name, i.type) for i in g.forward()], 'reverse': ['%s (%s)' % (i.name, i.type) for i in g.reverse()]}
            except Exception as exc:
                entry[graph] = str(exc)[:80]
        entry['channels'] = {name: replicator.channel(name).get() for name in replicator.channelNames
                             if not name.startswith(('pos', 'rot', 'scl', 'wpos', 'wrot', 'wscl', 'matrix', 'world'))
                             and isinstance(replicator.channel(name).get(), (int, float, str))}
        result['replicators'].append(entry)
    result['item_types'] = dict(collections.Counter(item.type for item in scene.items()))
    save()
    from moonray_modo import evaluated
    data = evaluated.capture(lx.service.Selection().GetTime())
    surfaces = data.get('surfaces', [])
    result['render_cache'] = {'surfaces': len(surfaces),
                              'by_source': dict(collections.Counter(names.get(s.get('source_item'), s.get('source_item')) for s in surfaces)),
                              'instanced': sum(1 for s in surfaces if s.get('instanced'))}
    save()
    from moonray_modo import host
    still = host.snapshot()
    result['still'] = summary(still)
    result['still']['by_source'] = {names.get(k, k): v for k, v in result['still']['by_source'].items()}
    save()
    pack(still, 'still')
    save()
    # Which copies Modo's render cache holds at the frame and a moment either side, as motion blur reads it.
    selection = lx.service.Selection()
    now = selection.GetTime()
    fps = float(scene.fps)
    moments = {}
    try:
        for label, offset in (('open', -0.25 / fps), ('frame', 0.0), ('close', 0.25 / fps)):
            held = evaluated.capture(now + offset)
            moments[label] = {(s.get('source_item'), s.get('instance_index')) for s in held.get('surfaces', [])}
        result['moments'] = {label: len(ids) for label, ids in moments.items()}
        result['only_at_frame'] = sorted(map(str, moments['frame'] - moments['open']))[:10]
        result['only_at_open'] = sorted(map(str, moments['open'] - moments['frame']))[:10]
        result['animated_channels'] = sorted({'%s.%s' % (i.name, c.name) for i in scene.items() for c in i.channels() if c.isAnimated})[:20]
    finally:
        selection.SetTime(now)
    save()
    # The three snapshots motion blur takes, each mesh's copies named as it names them, and where they differ.
    try:
        snaps = {}
        for label, offset in (('open', -0.25 / fps), ('frame', 0.0), ('close', 0.25 / fps)):
            selection.SetTime(now + offset)
            snaps[label] = {m.get('identity', m.get('name')): m for m in host.snapshot(evaluated_geometry=True).get('meshes', [])}
        selection.SetTime(now)
        differences = []
        for identity, mesh in snaps['frame'].items():
            for label in ('open', 'close'):
                other = snaps[label].get(identity)
                if other is None:
                    differences.append([str(identity), label, 'mesh missing']); continue
                a, b = mesh.get('instance_ids') or [], other.get('instance_ids') or []
                if set(a) != set(b):
                    differences.append([str(identity), label, len(a), len(b), sorted(set(a) - set(b))[:4], sorted(set(b) - set(a))[:4],
                                        len(a) - len(set(a)), len(b) - len(set(b))])
        result['mesh_counts'] = {label: len(meshes) for label, meshes in snaps.items()}
        result['instance_differences'] = differences[:12]
        result['instance_differences_count'] = len(differences)
    except Exception:
        result['instance_diff_error'] = traceback.format_exc()[-1500:]
    finally:
        selection.SetTime(now)
    save()
    from moonray_modo.animation import capture_frame
    try:
        moving = capture_frame(lx.service.Selection().GetTime(), True, True, float(scene.fps))
        result['motion'] = summary(moving)
        result['motion']['by_source'] = {names.get(k, k): v for k, v in result['motion']['by_source'].items()}
        pack(moving, 'motion')
    except Exception:
        result['motion'] = {'error': traceback.format_exc()[-2000:]}
except Exception:
    result['error'] = traceback.format_exc()
save()
