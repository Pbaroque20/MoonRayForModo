# python
"""Command line: a scene read as Surfaces: Modo evaluated geometry reads it (Modo's render cache, displaced by Modo for
MoonRay and XPU2, host.by_engine), beside its meshes as stored. PROBE_SCENE the .lxo; PROBE_ENGINE the engine read for
(moonray: displaced by Modo; moonlightipr: not). For each mesh read: its points, triangles and bounds; how long the
reading took; which effects each material's stack lays on, and the displacements the scene written for MoonRay
(rdla.scene_text, 480 pixels square at 4 samples) carries, for rendering outside Modo. PROBE_DISP_RATE sets Modo's
Displacement Rate (pixels) first: Modo's cut is far smaller at 8 than at the scene's 1. Writes test-results/evaluated-bounds/report.json and scene.rdla (PROBE_OUT for another folder)."""
import json
import os
import pathlib
import time
import traceback

import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\evaluated-bounds'))
out.mkdir(parents=True, exist_ok=True)
report = {}


def save():
    (out / 'report.json').write_text(json.dumps(report, indent=1, default=str))


def bounds(values):
    if not values:
        return None
    return [[round(min(p[i] for p in values), 3) for i in range(3)], [round(max(p[i] for p in values), 3) for i in range(3)]]


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    scene = modo.Scene()
    report['stored'] = {item.name: bounds([tuple(v.position) for v in item.geometry.vertices]) for item in scene.items('mesh')}
    save()
    if os.environ.get('PROBE_DISP_RATE'):
        scene.renderItem.channel('dispRate').set(float(os.environ['PROBE_DISP_RATE']))
    from moonray_modo import host, rdla
    with host.by_engine(os.environ.get('PROBE_ENGINE', 'moonray')):
        began = time.perf_counter()
        snapshot = host.snapshot(evaluated_geometry=True)
        report['snapshot_seconds'] = round(time.perf_counter() - began, 2)
    meshes = []
    for mesh in snapshot.get('meshes') or []:
        vertices = mesh.get('vertices') or []
        matrix = mesh.get('matrix')
        meshes.append({'name': mesh.get('name'), 'points': len(vertices), 'faces': len(mesh.get('faces') or []),
                       'bounds': bounds(vertices), 'matrix': matrix, 'subdivision': mesh.get('subdivision'),
                       'evaluated': mesh.get('evaluated_geometry')})
    report['meshes'] = meshes
    report['warnings'] = snapshot.get('warnings')
    report['stack_effects'] = {tag: [sorted({l.get('effect') for l in row.get('layers') or []}) for row in material.get('material_stack') or [material]]
                               for tag, material in (snapshot.get('materials') or {}).items()}
    save()
    began = time.perf_counter()
    text = rdla.scene_text(snapshot, 480, 480, 4, 0.0, str(out / 'out.exr'))
    report['rdla'] = {'seconds': round(time.perf_counter() - began, 2), 'bytes': len(text),
                      'displacements': [line for line in text.splitlines() if line.startswith('displacements[')]}
    (out / 'scene.rdla').write_text(text, encoding='utf-8')
except Exception:
    report['error'] = traceback.format_exc()
save()
