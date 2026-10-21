# python
"""Command-line test: where a scene's time goes before MoonRay starts rendering it (MOONRAY_PROBE_SCENE). Times the
scene's opening, the plugin's snapshot of it (host.snapshot), its textures' preparation (textures._prepare, each
timed), and the scene's writing as text and as text with binary geometry (rdlb.py); writes both into
test-results/cl-export/prep/<scene name>/ for MoonRay to be timed on them outside Modo."""
import json
import os
import pathlib
import time
import traceback
import lx

result = {}
try:
    source = pathlib.Path(os.environ['MOONRAY_PROBE_SCENE'])
    out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep') / source.stem
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    lx.eval('scene.open {%s} normal' % source)
    result['open_seconds'] = round(time.perf_counter() - started, 2)
    from moonray_modo import host, rdla, rdlb, textures
    prepared = []
    original = textures._prepare

    def timed(source, *args, **kwargs):
        began = time.perf_counter()
        try:
            return original(source, *args, **kwargs)
        finally:
            prepared.append((str(source), round(time.perf_counter() - began, 3)))
    textures._prepare = timed
    import cProfile, pstats, io

    def profiled(label, call):
        profile = cProfile.Profile()
        began = time.perf_counter()
        value = profile.runcall(call)
        result[label + '_seconds'] = round(time.perf_counter() - began, 2)
        held = io.StringIO()
        stats = pstats.Stats(profile, stream=held)
        stats.sort_stats('tottime').print_stats(22)
        stats.print_callers('_getfinalpathname|_import|deepcopy|object_values|transform_uv')
        (out / (label + '-profile.txt')).write_text(held.getvalue())
        return value
    if os.environ.get('MOONRAY_PROBE_PROFILE'):
        profile = cProfile.Profile(); began = time.perf_counter(); snapshot = profile.runcall(host.snapshot)
        result['snapshot_seconds'] = round(time.perf_counter() - began, 2)
        held = io.StringIO(); stats = pstats.Stats(profile, stream=held); stats.sort_stats('cumulative').print_stats(60)
        stats.sort_stats('tottime').print_stats(40)
        (out / 'snapshot-cumulative.txt').write_text(held.getvalue())
    else:
        began = time.perf_counter(); snapshot = host.snapshot(); result['snapshot_seconds'] = round(time.perf_counter() - began, 2)
    import pickle
    (out / 'snapshot.pickle').write_bytes(pickle.dumps(snapshot, protocol=4))
    if os.environ.get('MOONRAY_PROBE_SNAPSHOT_ONLY'):
        raise SystemExit
    snapshot['_geometry_revision'] = 'probe-1'   # as the preview panel gives each full reading
    result['meshes'] = len(snapshot.get('meshes', []))
    result['points'] = sum(len(m.get('vertices', [])) for m in snapshot.get('meshes', []))
    result['faces'] = sum(len(m.get('faces', [])) for m in snapshot.get('meshes', []))
    result['instances'] = sum(len(m.get('instances', []) or []) for m in snapshot.get('meshes', []))
    result['other_geometry'] = {k: len(v) for k, v in snapshot.items() if isinstance(v, list) and k in (
        'curves', 'points', 'hair', 'fur', 'replicators', 'volumes', 'vdbs', 'particles')}
    width, height = snapshot.get('width', 640), snapshot.get('height', 360)
    started = time.perf_counter()
    text = rdla.scene_text(snapshot, width, height, 2, 0.15, str(out / 'text.exr'))
    result['text_seconds'] = round(time.perf_counter() - started, 2)
    (out / 'text.rdla').write_text(text, encoding='utf-8')
    result['text_mb'] = round(len(text) / 2 ** 20, 1)
    result['textures_seconds'] = round(sum(s for _, s in prepared), 2)
    result['texture_calls'] = len(prepared)
    prepared.clear()
    started = time.perf_counter()
    with rdlb.collecting() as sink:
        split = rdla.scene_text(snapshot, width, height, 2, 0.15, str(out / 'split.exr'))
    (out / 'split.rdla').write_text(split, encoding='utf-8')
    sink.write(out / 'split.rdlb')
    result['split_seconds'] = round(time.perf_counter() - started, 2)
    result['split_text_mb'] = round(len(split) / 2 ** 20, 1)
    result['split_binary_mb'] = round((out / 'split.rdlb').stat().st_size / 2 ** 20, 1)
    # What is left in the text, by object kind: what else could go binary.
    kinds = {}
    current, size = None, 0
    for line in split.splitlines():
        stripped = line.strip()
        if '(' in stripped and stripped.endswith('{') and stripped.split('(')[0].replace('local ', '').split('=')[-1].strip().isidentifier():
            if current:
                kinds[current] = kinds.get(current, 0) + size
            current, size = stripped.split('(')[0].split('=')[-1].strip(), 0
        size += len(line) + 1
    if current:
        kinds[current] = kinds.get(current, 0) + size
    result['text_by_kind_mb'] = {k: round(v / 2 ** 20, 2) for k, v in sorted(kinds.items(), key=lambda kv: -kv[1])[:12]}
except SystemExit:
    pass
except Exception:
    result['error'] = traceback.format_exc()
# MOONRAY_PROBE_REPEAT: the scene read and written again in the same Modo, as a second render of it would be.
if os.environ.get('MOONRAY_PROBE_REPEAT') and 'error' not in result:
    try:
        began = time.perf_counter()
        again = host.snapshot()
        again['_geometry_revision'] = 'probe-2'
        result['repeat_snapshot_seconds'] = round(time.perf_counter() - began, 2)
        began = time.perf_counter()
        with rdlb.collecting() as sink:
            repeat = rdla.scene_text(again, width, height, 2, 0.15, str(out / 'split.exr'))
        payload = sink.payload()
        result['repeat_split_seconds'] = round(time.perf_counter() - began, 2)
        result['repeat_binary_same'] = payload == (out / 'split.rdlb').read_bytes()
        result['repeat_text_same'] = repeat == (out / 'split.rdla').read_text(encoding='utf-8')
    except Exception:
        result['repeat_error'] = traceback.format_exc()
pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\report.json').write_text(
    json.dumps(result, indent=1, default=str))
