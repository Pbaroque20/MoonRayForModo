# python
"""Command line: a scene as each engine reads it (host.snapshot under host.by_engine), plain and evaluated, pickled
for checks that render it without Modo (tools/check_moonlightipr_readings.py). PROBE_SCENE the .lxo, PROBE_OUT the
folder (test-results/engine-readings), PROBE_ENGINES the engines (moonlightipr moonray). Writes <engine>-<plain or
evaluated>.pickle and report.json: each reading's meshes (points, faces, material, matrix, subdivision) and warnings."""
import json
import os
import pathlib
import pickle
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\engine-readings'))
out.mkdir(parents=True, exist_ok=True)
report = {}


def mesh_summary(mesh):
    points = mesh.get('vertices') or []
    ys = [p[1] for p in points] if points else [0.0]
    xs = [p[0] for p in points] if points else [0.0]
    return {'identity': mesh.get('identity'), 'points': len(points), 'faces': len(mesh.get('faces') or []),
            'material': mesh.get('material'), 'matrix': mesh.get('matrix'), 'subdivision': mesh.get('subdivision'),
            'x_range': [min(xs), max(xs)], 'y_range': [min(ys), max(ys)], 'instances': len(mesh.get('instances') or [])}


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    from moonray_modo import host
    for engine in os.environ.get('PROBE_ENGINES', 'moonlightipr moonray').split():
        for evaluated in (False, True):
            name = '%s-%s' % (engine, 'evaluated' if evaluated else 'plain')
            try:
                with host.by_engine(engine):
                    snap = host.snapshot(evaluated_geometry=evaluated)
                (out / (name + '.pickle')).write_bytes(pickle.dumps(snap, protocol=4))
                report[name] = {'meshes': [mesh_summary(m) for m in snap.get('meshes') or []],
                                'warnings': list(snap.get('warnings') or [])[:12]}
            except Exception:
                report[name] = {'error': traceback.format_exc()[-1500:]}
except Exception:
    report['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(report, indent=1, default=str))
