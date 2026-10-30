# python
"""Command-line test: a mesh edit read from the live render cache (evaluated.capture, the adapter's
MR_geometry_live_*), against the same edit read from a cache made anew. MOONRAY_PROBE_SCENE is read whole (which
starts the live cache), one mesh of some thousands of points is moved with Modo's move tool, and its surfaces are read
again: from the live cache where it heard the edit, with the Shader Tree's stacks kept (host.snapshot, shading_kept).
The edited mesh's points and every surface's place must be the same both ways. Writes MOONRAY_PROBE_OUT/live.json."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT', 'test-results/cl-export/live'))
out.mkdir(parents=True, exist_ok=True)
result = {}


def timed(name, call):
    began = time.perf_counter()
    value = call()
    result[name + '_seconds'] = round(time.perf_counter() - began, 3)
    return value


try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    from moonray_modo import host, evaluated
    whole = timed('whole', lambda: host.snapshot(evaluated_geometry=True))
    result['live_started'] = evaluated.LIVE['started']
    cache = dict(whole, meshes=[dict(m) for m in whole['meshes']])
    sized = sorted((len(m['vertices']), m['identity'].split('|')[0]) for m in whole['meshes'])
    chosen = next((name for count, name in sized if count >= 4000), sized[-1][1])
    result['edited'] = chosen
    lx.eval('select.item {%s} set' % chosen)
    lx.eval('select.typeFrom vertex')
    lx.eval('select.drop vertex')
    lx.eval('tool.set TransformMove on')
    lx.eval('tool.attr xfrm.transform TY 0.01')
    lx.eval('tool.doApply')
    lx.eval('tool.set TransformMove off')
    lx.eval('select.typeFrom item')
    before = dict(evaluated.LIVE)
    edited = timed('edit_read', lambda: host.snapshot(evaluated_geometry=True, reuse_geometry=cache, refresh_materials=True,
                                                     dirty_meshes={chosen}, shading_kept=True))
    result['live'] = {'served': evaluated.LIVE['served'] - before['served'], 'refused': evaluated.LIVE['refused'] - before['refused']}
    result['edit_adapter_timing'] = edited.get('_evaluated_data', {}).get('timing')
    # The same state read from a cache made anew (the live cache let go first).
    evaluated.stop_live()
    fresh = timed('fresh_read', lambda: host.snapshot(evaluated_geometry=True))
    mine = {m['identity']: m for m in edited['meshes']}
    theirs = {m['identity']: m for m in fresh['meshes']}
    result['meshes'] = [len(mine), len(theirs)]
    result['missing'] = sorted(set(theirs) - set(mine))[:5]
    differ_points = [k for k in theirs if k in mine and k.startswith(chosen + '|') and list(mine[k]['vertices']) != list(theirs[k]['vertices'])]
    differ_place = [k for k in theirs if k in mine and (mine[k].get('matrix') != theirs[k].get('matrix') or mine[k].get('instances') != theirs[k].get('instances'))]
    differ_material = [k for k in theirs if k in mine and mine[k].get('material') != theirs[k].get('material')]
    result['edited_points_differ'] = differ_points
    result['places_differ'] = differ_place[:5]
    result['materials_differ'] = differ_material[:5]
    moved = [k for k in theirs if k.startswith(chosen + '|') and k in cache_ids] if False else None
    result['edited_points_changed'] = any(list(m['vertices']) != list(next((c for c in cache['meshes'] if c['identity'] == m['identity']), m)['vertices'])
                                          for m in edited['meshes'] if m['identity'].startswith(chosen + '|'))
except Exception:
    result['error'] = traceback.format_exc()
(out / 'live.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
