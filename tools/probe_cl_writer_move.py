# python
"""Command-line test: what writing MOONRAY_PROBE_SCENE's text for the renderer costs after a move (rdla.scene_text,
as the scene writer runs it for MoonRay's previews): written once, a part moved as a move's quick path
follows it (incremental.refresh_transforms), written again, profiled; and how much of the text the move changed
(scene_delta.difference). Writes MOONRAY_PROBE_OUT/writer.json."""
import cProfile
import io
import json
import os
import pathlib
import pstats
import time
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT', 'test-results/cl-export/writer'))
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    from moonray_modo import host, rdla, rdlb, incremental
    from moonray_modo.scene_delta import difference
    snapshot = host.snapshot(evaluated_geometry=True)
    # MOONRAY_PROBE_LIMIT_MB: the encodings' cache this large, to find what the scene's lists take.
    if os.environ.get('MOONRAY_PROBE_LIMIT_MB'):
        from moonray_modo import serialization as kept_lists
        kept_lists.LIMIT = int(os.environ['MOONRAY_PROBE_LIMIT_MB']) * 2 ** 20

    def write(scene):
        # As the panel writes it: the scene's lists kept encoded from one write to the next (its _geometry_revision).
        with rdlb.collecting() as sink:
            text = rdla.scene_text(dict(scene, _geometry_revision='probe'), 640, 360, 4, 0.15, None)
        return text, sink

    began = time.perf_counter()
    first, sink = write(snapshot)
    result['first_seconds'] = round(time.perf_counter() - began, 3)
    part = next(m['identity'].split('|')[0] for m in snapshot['meshes'] if len(m['vertices']) >= 2000)
    lx.eval('select.item {%s} set' % part)
    lx.eval('transform.channel pos.X 0.05')
    moved = dict(snapshot, meshes=[dict(m) for m in snapshot['meshes']])
    incremental.refresh_transforms(modo.Scene(), moved, None)
    # Which kept lists the second write did not find (serialization.array), by kind and the list's type.
    from moonray_modo import serialization
    result['kept_after_first'] = {'entries': len(serialization._cache), 'megabytes': round(serialization._bytes / 2 ** 20, 1),
                                  'limit_megabytes': serialization.LIMIT // 2 ** 20}
    sample = next(m for m in moved['meshes'] if type(m['vertices']).__name__ == 'Rows')
    result['sample_points_kept'] = any(key[1] == id(sample['vertices']) for key in serialization._cache)
    from collections import Counter
    misses = Counter()
    keep = serialization.array

    def counted(kind, source, encode):
        entry = serialization._cache.get((kind, id(source)))
        if entry is None or entry[0] is not source:
            misses[(kind.split(':')[0], type(source).__name__)] += 1
        return keep(kind, source, encode)
    serialization.array = counted
    rdla._kept = counted
    rdlb._cached = counted
    profile = cProfile.Profile()
    began = time.perf_counter()
    profile.enable()
    second, sink = write(moved)
    profile.disable()
    result['misses'] = [(list(k), v) for k, v in misses.most_common(12)]
    result['second_seconds'] = round(time.perf_counter() - began, 3)
    began = time.perf_counter()
    delta = difference(first, second, sink.text_of)
    result['difference_seconds'] = round(time.perf_counter() - began, 3)
    result['text_bytes'] = len(second)
    result['delta_bytes'] = len(delta) if delta is not None else None
    result['delta_head'] = (delta or '')[:400]
    text = io.StringIO()
    pstats.Stats(profile, stream=text).sort_stats('cumulative').print_stats(35)
    result['profile'] = [line for line in text.getvalue().splitlines() if line.strip()][:60]
except Exception:
    result['error'] = traceback.format_exc()
(out / 'writer.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
