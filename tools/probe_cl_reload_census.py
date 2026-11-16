# python
"""Command line: what a second load of a scene costs, and how many of its meshes depend only on themselves.

Opens MOONRAY_PROBE_SCENE and writes test-results/reload-census/<MOONRAY_PROBE_LABEL>/:
- census: each mesh-like item, whether something deforms it, drives or animates its own channels, or moves it (its
  transforms or a parent's driven or keyed), with its face count; the item kinds that make the kit read the scene whole.
- clean: a whole reading (host.snapshot) with the scene unsaved-change free, under cProfile; what the Scene cache's
  hit costs (key, pickle, file signature).
- edited: one mesh moved 1 mm (an unsaved change, so the Scene cache refuses), then a whole reading again: what an
  IPR restart after a tweak costs today.
- keys: what reading each mesh's own (unevaluated) geometry counts costs, the start of a per-mesh key."""
import cProfile
import io
import json
import os
import pathlib
import pickle
import pstats
import time
import traceback
import lx
import modo

label = os.environ.get('MOONRAY_PROBE_LABEL', 'scene')
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\reload-census') / label
out.mkdir(parents=True, exist_ok=True)
result = {'scene': os.environ['MOONRAY_PROBE_SCENE']}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')


def profiled(name, call):
    profile = cProfile.Profile()
    began = time.perf_counter()
    profile.enable()
    value = call()
    profile.disable()
    seconds = time.perf_counter() - began
    text = io.StringIO()
    stats = pstats.Stats(profile, stream=text)
    stats.sort_stats('cumulative').print_stats(60)
    text.write('\n---- by own time ----\n')
    stats.sort_stats('tottime').print_stats(40)
    (out / (name + '.txt')).write_text(text.getvalue(), encoding='utf-8')
    # Own time by kit module, and the cumulative time of the kit's top-level steps.
    modules, steps = {}, {}
    for (path, line, func), (cc, nc, tt, ct, callers) in stats.stats.items():
        key = os.path.basename(path) if 'moonray_modo' in path else ('<builtin>' if path == '~' else 'other')
        modules[key] = modules.get(key, 0.0) + tt
        if 'moonray_modo' in path:
            steps['%s:%s' % (os.path.basename(path), func)] = max(steps.get('%s:%s' % (os.path.basename(path), func), 0.0), ct)
    result[name] = {'seconds': round(seconds, 3),
                    'own_by_module': {k: round(v, 3) for k, v in sorted(modules.items(), key=lambda kv: -kv[1])[:20]},
                    'cumulative_steps': {k: round(v, 3) for k, v in sorted(steps.items(), key=lambda kv: -kv[1])[:40]}}
    save()
    return value


class Quick(Exception):
    pass


def changed():
    return int(lx.eval1('query sceneservice scene.changed ? current'))


try:
    began = time.perf_counter()
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    result['open_seconds'] = round(time.perf_counter() - began, 3)
    scene = modo.Scene()
    from moonray_modo import host, incremental, scene_reading

    # ---- census ----
    began = time.perf_counter()
    kinds = {}
    for item in scene.iterItems():
        kinds[item.type] = kinds.get(item.type, 0) + 1
    result['item_kinds'] = dict(sorted(kinds.items(), key=lambda kv: -kv[1]))
    known = set(incremental.STEADY) | set(incremental.NEUTRAL)
    service = lx.service.Scene()
    light_types = [service.ItemTypeLookup(name) for name in ('light', 'textureLayer')]
    blocking = {}
    for item in scene.iterItems():
        kind = item.type
        if kind in known or kind.startswith(('material.', 'moonray.', 'cm')) or any(item.TestType(t) for t in light_types):
            continue
        blocking[kind] = blocking.get(kind, 0) + 1
    result['kinds_that_force_whole_reads'] = blocking
    result['steady'] = incremental.steady(scene)
    result['own_geometry'] = incremental.own_geometry(scene)
    bent = incremental.deformed_meshes(scene) or set()
    graph = lx.object.ChannelGraph(lx.object.Scene(scene).GraphLookup(lx.symbol.sGRAPH_CHANLINKS))

    def driven_or_keyed(item):
        """Whether any of the item's own channels is linked from another (a channel modifier, a link) or keyed."""
        raw = lx.object.Item(item)
        for index in range(raw.ChannelCount()):
            try:
                if graph.RevCount(raw, index) > 0:
                    return 'driven'
            except Exception:
                pass
        try:
            # Modo's computed outputs (world matrices, glstate) report as animated: not keys.
            keyed = [channel.name for channel in item.channels() if channel.isAnimated and not channel.name.endswith('Matrix') and channel.name != 'glstate']
            if keyed:
                KEYED[item.id] = keyed[:8]
                return 'keyed'
        except Exception:
            pass
        return None

    memo = {}
    KEYED = {}

    def moves(item):
        """Whether the item's place can change without an edit: its transform items, or a parent's, driven or keyed."""
        if item is None:
            return None
        if item.id in memo:
            return memo[item.id]
        memo[item.id] = None
        why = None
        try:
            for transform in item.transforms:
                why = driven_or_keyed(transform)
                if why:
                    break
        except Exception:
            pass
        if not why:
            why = moves(item.parent)
        memo[item.id] = why
        return why

    census = []
    for item in scene.items('mesh', superType=False) + scene.items('meshInst', superType=False):
        entry = {'name': item.name, 'type': item.type}
        try:
            entry['faces'] = item.geometry.numPolygons if item.type == 'mesh' else None
        except Exception:
            entry['faces'] = None
        if item.type == 'meshInst':
            try:
                sources = item.itemGraph('meshInst').reverse()
                entry['source'] = sources[0].name if sources else None
            except Exception:
                entry['source'] = None
        entry['deformed'] = item.id in bent
        entry['own_channels'] = driven_or_keyed(item)
        entry['moves'] = moves(item)
        entry['keyed_channels'] = KEYED.get(item.id)
        census.append(entry)
    (out / 'census.json').write_text(json.dumps(census, indent=1), encoding='utf-8')

    def tally(entries):
        geometry_own = [e for e in entries if not e['deformed'] and not e['own_channels']]
        return {'items': len(entries), 'faces': sum(e['faces'] or 0 for e in entries),
                'geometry_own': len(geometry_own), 'geometry_own_faces': sum(e['faces'] or 0 for e in geometry_own),
                'deformed': sum(e['deformed'] for e in entries), 'own_channels_driven': sum(e['own_channels'] == 'driven' for e in entries),
                'own_channels_keyed': sum(e['own_channels'] == 'keyed' for e in entries),
                'placement_moves': sum(bool(e['moves']) for e in entries)}
    result['census'] = {'mesh': tally([e for e in census if e['type'] == 'mesh']),
                        'meshInst': tally([e for e in census if e['type'] == 'meshInst'])}
    result['census_seconds'] = round(time.perf_counter() - began, 3)
    save()

    # ---- per-mesh key start: each mesh's own counts ----
    began = time.perf_counter()
    points = 0
    for item in scene.items('mesh', superType=False):
        try:
            points += item.geometry.numVertices
        except Exception:
            pass
    result['keys'] = {'counts_seconds': round(time.perf_counter() - began, 3), 'points': points,
                      'raw_bytes_positions': points * 12}
    save()

    # ---- the Scene cache key's parts ----
    parts = {}
    for name, call in (('changed', lambda: lx.eval1('query sceneservice scene.changed ? current')),
                       ('file', lambda: lx.eval1('query sceneservice scene.file ? current')),
                       ('time', lambda: lx.service.Selection().GetTime()),
                       ('reading_code', scene_reading.reading_code),
                       ('modo_displaces', lambda: __import__('moonray_modo.host', fromlist=['x']).modo_displaces()),
                       ('scene_cache_pref', lambda: __import__('moonray_modo.cache_folder', fromlist=['x']).scene_cache()),
                       ('whole_key', lambda: scene_reading.key(True))):
        began = time.perf_counter()
        try:
            call()
        except Exception as exc:
            parts[name + '_error'] = str(exc)
        parts[name] = round(time.perf_counter() - began, 3)
    result['key_parts'] = parts
    save()
    if os.environ.get('MOONRAY_PROBE_QUICK'):
        raise Quick

    # ---- clean whole reading ----
    result['changed_before'] = changed()
    shot = profiled('clean', lambda: host.snapshot(evaluated_geometry=True))
    result['meshes_read'] = len(shot.get('meshes') or [])
    began = time.perf_counter()
    held_key = scene_reading.key(True)
    result['cache_key_seconds'] = round(time.perf_counter() - began, 3)
    result['cache_key_given'] = held_key is not None
    began = time.perf_counter()
    scene_reading._file_digest(os.environ['MOONRAY_PROBE_SCENE'])
    result['file_digest_seconds'] = round(time.perf_counter() - began, 3)
    began = time.perf_counter()
    frozen = pickle.dumps(shot, protocol=pickle.HIGHEST_PROTOCOL)
    result['freeze_seconds'] = round(time.perf_counter() - began, 3)
    result['frozen_mb'] = round(len(frozen) / 1e6, 1)
    began = time.perf_counter()
    from moonray_modo import evaluated  # noqa: F401
    pickle.loads(frozen)
    result['thaw_seconds'] = round(time.perf_counter() - began, 3)
    began = time.perf_counter()
    scene_reading.files(shot)
    result['signature_seconds'] = round(time.perf_counter() - began, 3)
    del frozen, shot
    save()

    # ---- one unsaved tweak, then a whole reading again (an IPR restart after it) ----
    target = next((m for m in scene.items('mesh', superType=False) if m.parent is None or True), None)
    x = target.position.x.get()
    target.position.x.set(x + 0.001)
    result['edited_item'] = target.name
    result['changed_after_edit'] = changed()
    result['cache_key_after_edit'] = scene_reading.key(True) is not None
    shot = profiled('edited', lambda: host.snapshot(evaluated_geometry=True))
    result['meshes_read_after_edit'] = len(shot.get('meshes') or [])
except Quick:
    pass
except Exception:
    result['error'] = traceback.format_exc()
save()
