# python
"""Command-line test: a mesh carrying many weight maps that nothing reads, as a rig's bone weights are (a tester's model
had dozens, and MoonRay slowed to a crawl). Reads its maps all (as before), by one name, and by none
(vertex_maps.read); then the scene as the preview reads it (host.snapshot: only the maps the scene reads,
host.painted_wanted) and as it was read before (every map), each written for MoonRay (rdla.scene_text), with how long
each took and how large the scene came to. Writes test-results/cl-weight-maps/report.json (PROBE_OUT for another
folder); PROBE_MAPS maps (40), on a sphere of PROBE_SIDES sides (96)."""
import json
import os
import pathlib
import time
import traceback
from unittest import mock

import lx
import modo

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-weight-maps'))
out.mkdir(parents=True, exist_ok=True)
result = {}
MAPS = int(os.environ.get('PROBE_MAPS', 40))
SIDES = int(os.environ.get('PROBE_SIDES', 96))


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


def timed(call):
    began = time.perf_counter()
    value = call()
    return value, round(time.perf_counter() - began, 3)


try:
    lx.eval('layer.new')
    lx.eval('tool.set prim.sphere on')
    lx.eval('tool.attr prim.sphere sides %d' % SIDES)
    lx.eval('tool.attr prim.sphere segments %d' % (SIDES // 2))
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.sphere off')
    item = modo.Scene().selected[-1]
    geometry = item.geometry
    count = geometry.numVertices
    for k in range(MAPS):
        weights = geometry.vmaps.addWeightMap('Bone%02d' % k, 0.0)
        # Each bone's weight rising along the sphere's height at its own rate, so no two maps are alike.
        for point in geometry.vertices:
            weights[point.index] = (min(1.0, max(0.0, (point.position[1] + 1.0) * (k + 1) / MAPS)),)
    geometry.setMeshEdits()
    result['mesh'] = {'points': count, 'maps': MAPS}
    save()

    from moonray_modo import host, rdla, vertex_maps
    mesh = modo.meshgeometry.MeshProvider.meshFromMeshChannel(item._item, 'deformed')
    every, seconds_every = timed(lambda: vertex_maps.read(mesh))
    one, seconds_one = timed(lambda: vertex_maps.read(mesh, {'Bone07', 'not a map'}))
    none, seconds_none = timed(lambda: vertex_maps.read(mesh, set()))
    result['read'] = {'every': [len(every), seconds_every], 'one': [sorted(one), seconds_one], 'none': [len(none), seconds_none],
                      'names_of': len(vertex_maps.names_of(mesh)), 'named_reader': vertex_maps._library(True) is not None}
    save()

    def reading(label, wanted):
        if wanted is None:
            with mock.patch.object(host, 'painted_wanted', lambda found: None):
                snapshot, seconds = timed(lambda: host.snapshot(evaluated_geometry=False))
        else:
            snapshot, seconds = timed(lambda: host.snapshot(evaluated_geometry=False))
        shaped = [m for m in snapshot.get('meshes') or [] if m.get('_vertex_maps')]
        text, written = timed(lambda: rdla.scene_text(snapshot, 64, 64, 1, 0.0, str(out / 'out.exr')))
        (out / (label + '.rdla')).write_text(text, encoding='utf-8')
        result.setdefault('scene', {})[label] = {
            'read_seconds': seconds, 'write_seconds': written, 'rdla_bytes': len(text),
            'attributes': sorted(set(name for m in shaped for name in list(m.get('point_attributes') or {}) + list(m.get('corner_attributes') or {}))),
            'maps_known': max((len(m['_vertex_maps']) for m in shaped), default=0)}
        save()
    reading('now', True)
    reading('before', None)
except Exception:
    result['error'] = traceback.format_exc()
save()
