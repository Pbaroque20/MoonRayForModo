# python
"""Command-line test: what a reading of MOONRAY_PROBE_SCENE costs, as Modo evaluates its geometry, whole and in part.
A whole reading (host.snapshot), one that reads a single mesh again (dirty_meshes, as a one-mesh edit does), and asking
every item where it stands (what a move needs), each timed and profiled: the adapter's own part and Python's, with the
functions that took longest. Writes MOONRAY_PROBE_OUT/partial.json."""
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

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT', 'test-results/cl-export/partial'))
out.mkdir(parents=True, exist_ok=True)
result = {}


def profiled(name, call):
    profile = cProfile.Profile()
    began = time.perf_counter()
    profile.enable()
    try:
        value = call()
    finally:
        profile.disable()
    result[name + '_seconds'] = round(time.perf_counter() - began, 3)
    text = io.StringIO()
    pstats.Stats(profile, stream=text).sort_stats('cumulative').print_stats(30)
    result[name + '_profile'] = [line for line in text.getvalue().splitlines() if line.strip()][:60]
    return value


try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    from moonray_modo import host
    whole = profiled('whole', lambda: host.snapshot(evaluated_geometry=True))
    result['meshes'] = len(whole['meshes'])
    cache = dict(whole, meshes=[dict(m) for m in whole['meshes']])
    named = sorted({m['identity'].split('|')[0] for m in whole['meshes']})
    # A mesh about as big as the one the GUI probe edits (some thousands of points).
    sized = sorted((len(m['vertices']), m['identity'].split('|')[0]) for m in whole['meshes'])
    chosen = next((name for count, name in sized if count >= 4000), sized[-1][1])
    result['dirty'] = chosen
    # The adapter's own times (evaluating, listing, the prototypes; loading, fetching, writing), and whether the partial
    # reading fell back to a whole one (evaluated.capture reads whole where a kept prototype is not in the reading before).
    from moonray_modo import evaluated
    readings = []
    capture = evaluated.capture

    def timed_capture(*a, **k):
        data = capture(*a, **k)
        readings.append({'only': bool(k.get('only')), 'timing': data.get('timing'), 'handing': data.get('handing'),
                         'kept': sum(1 for held in data.get('prototypes', {}).values() if held.get('kept'))})
        return data
    evaluated.capture = timed_capture
    result['whole_adapter'] = {'timing': whole.get('_evaluated_data', {}).get('timing'), 'handing': whole.get('_evaluated_data', {}).get('handing'),
                               'prototypes': len(whole.get('_evaluated_data', {}).get('prototypes', {})),
                               'with_item': sum(1 for held in whole.get('_evaluated_data', {}).get('prototypes', {}).values() if 'item' in held)}
    profiled('one_mesh', lambda: host.snapshot(evaluated_geometry=True, reuse_geometry=cache, refresh_materials=True, dirty_meshes={chosen}))
    result['one_mesh_readings'] = readings
    from moonray_modo.host import world_matrix
    scene = modo.Scene()
    profiled('placements', lambda: [world_matrix(scene.item(name)) for name in named])
    result['items'] = len(named)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'partial.json').write_text(json.dumps(result, indent=1, default=str))
lx.eval('!app.quit')
