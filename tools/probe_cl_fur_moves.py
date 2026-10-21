# python
"""Command-line test: a scene read as Modo evaluates it (MOONRAY_PROBE_SCENE), whether its meshes and fur stand
with their items (incremental.stands_with_items, which lets a move be followed without reading the meshes again),
how long a whole reading and a move's reading take, and a whole reading again once a cube is added. Writes test-results/cl-export/prep/fur_moves.json."""
import json
import os
import pathlib
import time
import traceback
import lx
import modo

result = {}
out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\cl-export\prep\fur_moves.json')
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    from moonray_modo import host, incremental
    began = time.perf_counter()
    snapshot = host.snapshot(evaluated_geometry=True)
    result['whole_seconds'] = round(time.perf_counter() - began, 3)
    result['extra'] = [(e.get('kind'), e.get('source_item'), len(e.get('counts', []))) for e in snapshot.get('extra_geometry', [])]
    result['stands'] = incremental.stands_with_items(modo.Scene(), snapshot)
    result['rigid'] = incremental.rigid(modo.Scene(), snapshot)
    item = modo.Scene().item(os.environ.get('MOONRAY_PROBE_ITEM', 'mesh038'))
    lx.eval('transform.channel pos.X 0.5 set %s' % item.id)
    began = time.perf_counter()
    again = host.snapshot(evaluated_geometry=True, reuse_geometry=dict(snapshot))
    incremental.refresh_transforms(modo.Scene(), again, [item.id])
    result['move_seconds'] = round(time.perf_counter() - began, 3)
    result['fur_moved'] = [e['matrix'][12:15] for e in again.get('extra_geometry', [])]
    lx.eval('layer.new')
    lx.eval('tool.set prim.cube on')
    lx.eval('tool.attr prim.cube sizeX 0.5')
    lx.eval('tool.doApply')
    lx.eval('tool.set prim.cube off')
    began = time.perf_counter()
    added = host.snapshot(evaluated_geometry=True)
    result['added_seconds'] = round(time.perf_counter() - began, 3)
    result['added_meshes'] = len(added['meshes'])
except Exception:
    result['error'] = traceback.format_exc()
out.write_text(json.dumps(result, indent=1))
