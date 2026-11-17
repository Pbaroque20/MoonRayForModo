# python
"""Command line: why a scene is or is not rigid for the shutter (incremental.rigid), which decides whether the ends of
the shutter are read whole or only where the items stand. PROBE_SCENE the .lxo (the Lamborghini unless named);
PROBE_ENGINE the reading rule (moonlightipr unless named). Writes test-results/rigid-census/<scene stem>.json: the item
kinds that are not steady (with a few names each), the deformers, the animated items, the meshes that stand apart from
their items, the projections, the time of a whole reading and of one at a shutter end with the meshes kept, and the
meshes named like wheels and tyres (their instances, matrices' scale, sizes, subdivision) under each engine's rule."""
import json
import math
import os
import pathlib
import time
import traceback
import lx

scene_path = os.environ.get('PROBE_SCENE', r'C:\Users\Raphael Tobar\Downloads\Lamborghini(1)\Lamborghini_Moonray.lxo')
engine = os.environ.get('PROBE_ENGINE', 'moonlightipr')
out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\rigid-census'))
out.mkdir(parents=True, exist_ok=True)
report = {'scene': scene_path, 'engine': engine}


def save():
    (out / (pathlib.Path(scene_path).stem + '.json')).write_text(json.dumps(report, indent=1, default=str))


def scale_of(matrix):
    if not matrix or len(matrix) != 16:
        return None
    return [round(math.sqrt(sum(matrix[r * 4 + c] ** 2 for c in range(3))), 4) for r in range(3)]


def wheels(snapshot):
    found = []
    for mesh in snapshot.get('meshes') or []:
        name = str(mesh.get('name', '')).lower()
        if not any(word in name for word in ('tyre', 'tire', 'wheel', 'rim', 'rubber')):
            continue
        points = mesh.get('vertices') or []
        spans = [round(max(p[a] for p in points) - min(p[a] for p in points), 4) for a in range(3)] if points else None
        instances = mesh.get('instances') or []
        found.append({'name': mesh.get('name'), 'identity': mesh.get('identity'), 'points': len(points),
                      'faces': len(mesh.get('faces') or []), 'subdivision': mesh.get('subdivision'),
                      'subdivision_level': mesh.get('subdivision_level'), 'spans': spans,
                      'matrix_scale': scale_of(mesh.get('matrix')), 'instances': len(instances),
                      'instance_scales': [scale_of(m) for m in instances[:6]],
                      'material': mesh.get('material')})
    return found


try:
    began = time.monotonic()
    lx.eval('!scene.open {%s} normal' % scene_path)
    report['open_seconds'] = round(time.monotonic() - began, 2)
    import modo
    from moonray_modo import host, incremental
    scene = modo.Scene()
    service = lx.service.Scene()
    kinds = [service.ItemTypeLookup(name) for name in ('light', 'textureLayer')]
    unsteady = {}
    for item in scene.iterItems():
        kind = item.type
        if kind in incremental.STEADY or kind.startswith(('material.', 'moonray.')) or any(item.TestType(each) for each in kinds):
            continue
        entry = unsteady.setdefault(kind, {'count': 0, 'names': []})
        entry['count'] += 1
        if len(entry['names']) < 6:
            entry['names'].append(item.name)
    report['unsteady_kinds'] = unsteady
    report['neutral'] = sorted(incremental.NEUTRAL)
    report['deformers'] = incremental.deformers(scene)
    try:
        report['deformers_found'] = [(item.type, item.name) for item in scene.items('deform', superType=True)][:30]
    except Exception:
        report['deformers_found'] = traceback.format_exc()[-300:]
    bent = incremental.deformed_meshes(scene)
    report['deformed_meshes'] = None if bent is None else [scene.item(identity).name for identity in sorted(bent)][:40]
    report['steady'] = incremental.steady(scene)
    report['own_geometry'] = incremental.own_geometry(scene)
    keyed = []
    report['items'] = len(list(scene.iterItems()))
    clock = time.monotonic()
    for item in scene.iterItems():
        try:
            channels = [channel.name for channel in item.channels() if channel.isAnimated]
        except Exception:
            continue
        if channels:
            keyed.append({'name': item.name, 'type': item.type, 'channels': channels[:8]})
    report['animated_items'] = keyed[:60]
    report['animated_count'] = len(keyed)
    report['animated_seconds'] = round(time.monotonic() - clock, 2)
    # The same asked through the SDK, channel by channel (Envelope): how fast it can be told that nothing is keyed.
    clock = time.monotonic()
    enveloped = 0
    try:
        read = lx.object.Scene(scene).Channels(lx.symbol.s_ACTIONLAYER_EDIT, 0.0)
        for item in scene.iterItems():
            raw = lx.object.Item(item)
            for index in range(raw.ChannelCount()):
                try:
                    if read.IsAnimated(raw, index):
                        enveloped += 1
                except Exception:
                    pass
        report['sdk_animated_channels'] = enveloped
    except Exception:
        report['sdk_animated_error'] = traceback.format_exc()[-400:]
    report['sdk_animated_seconds'] = round(time.monotonic() - clock, 2)
    save()
    for rule in (engine, 'moonray' if engine != 'moonray' else 'moonlightipr'):
        entry = report.setdefault('readings', {}).setdefault(rule, {})
        import cProfile
        import io
        import pstats
        first = cProfile.Profile()
        began = time.monotonic()
        with host.by_engine(rule):
            first.enable()
            snapshot = host.snapshot(evaluated_geometry=False)
            first.disable()
        entry['whole_seconds'] = round(time.monotonic() - began, 2)
        text = io.StringIO()
        pstats.Stats(first, stream=text).sort_stats('cumulative').print_stats(45)
        entry['first_profile_cumulative'] = text.getvalue().splitlines()[:80]
        save()
        entry['meshes'] = len(snapshot.get('meshes') or [])
        entry['instanced_meshes'] = sum(1 for mesh in snapshot.get('meshes') or [] if 'instances' in mesh)
        entry['shutter'] = {key: snapshot['camera'].get(key) for key in ('shutter_length', 'shutter_offset', 'motion_blur')}
        followed, loose = incremental.standing(scene, snapshot)
        entry['standing'] = {'followed': followed, 'loose': [scene.item(identity).name for identity in sorted(loose)][:30],
                             'loose_count': len(loose)}
        from moonray_modo.coordinates import descriptors
        entry['projections'] = sorted({d.get('projection', 'uv') for d in descriptors(snapshot.get('materials') or {}).values()})
        entry['rigid'] = incremental.rigid(scene, snapshot)
        entry['extra_geometry'] = [(item.get('kind'), bool(item.get('source_item'))) for item in snapshot.get('extra_geometry') or []][:20]
        began = time.monotonic()
        with host.by_engine(rule):
            again = host.snapshot(evaluated_geometry=False, reuse_geometry=snapshot)
        entry['kept_meshes_seconds'] = round(time.monotonic() - began, 2)
        # The whole reading again, profiled: where a reading of the scene with its meshes known spends its time.
        import cProfile
        import io
        import pstats
        profile = cProfile.Profile()
        began = time.monotonic()
        with host.by_engine(rule):
            profile.enable()
            host.snapshot(evaluated_geometry=False)
            profile.disable()
        entry['whole_again_seconds'] = round(time.monotonic() - began, 2)
        text = io.StringIO()
        pstats.Stats(profile, stream=text).sort_stats('cumulative').print_stats(45)
        entry['profile_cumulative'] = text.getvalue().splitlines()[:80]
        text = io.StringIO()
        pstats.Stats(profile, stream=text).sort_stats('tottime').print_stats(30)
        entry['profile_own'] = text.getvalue().splitlines()[:60]
        entry['wheels'] = wheels(snapshot)
        save()
except Exception:
    report['error'] = traceback.format_exc()
report['done'] = True
save()
