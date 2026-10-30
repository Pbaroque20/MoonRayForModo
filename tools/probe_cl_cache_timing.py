# python
"""Command-line test: what Modo's render cache evaluation costs for MOONRAY_PROBE_SCENE, by how the cache is asked (the
adapter's MR_geometry_cache_timing): with and without displacement, a forced full update or not, each twice (Modo's own
caches warm), and again after one mesh's points are moved (a mesh edit's case). Writes MOONRAY_PROBE_OUT/timing.json."""
import ctypes
import json
import os
import pathlib
import traceback
import lx
import modo

out = pathlib.Path(os.environ.get('MOONRAY_PROBE_OUT', 'test-results/cl-export/timing'))
out.mkdir(parents=True, exist_ok=True)
result = {}
TRACK, OFF, FORCE, DISPLACE = 0x100, 0x200, 0x400, 0x1
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    from moonray_modo import evaluated
    bridge = evaluated._load()
    call = bridge.MR_geometry_cache_timing
    call.argtypes = [ctypes.c_double, ctypes.c_uint, ctypes.c_int, ctypes.c_int]
    call.restype = ctypes.c_char_p
    time = lx.service.Selection().GetTime()

    def ask(name, flags, force, boxes=0):
        result.setdefault(name, []).append(json.loads(call(time, flags, force, boxes).decode('utf-8')))
    for _ in range(2):
        ask('as the kit asks (forced, displaced)', TRACK | OFF | FORCE | DISPLACE, 1)
        ask('not displaced', TRACK | OFF | FORCE, 1)
        ask('no forced flag, update forced', TRACK | OFF | DISPLACE, 1)
        ask('no forced flag, update not forced', TRACK | OFF | DISPLACE, 0)
        ask('as the kit asks, with boxes', TRACK | OFF | FORCE | DISPLACE, 1, 1)
    # A mesh edit: one mesh of some thousands of points moved, then the cache as the kit asks again.
    meshes = sorted(((len(modo.Mesh(m).geometry.vertices), m) for m in modo.Scene().items('mesh')), key=lambda e: e[0])
    chosen = next((m for n, m in meshes if n >= 4000), meshes[-1][1])
    lx.eval('select.item {%s} set' % chosen.id)
    lx.eval('select.typeFrom vertex')
    lx.eval('select.drop vertex')
    lx.eval('tool.set TransformMove on')
    lx.eval('tool.attr xfrm.transform TY 0.01')
    lx.eval('tool.doApply')
    lx.eval('tool.set TransformMove off')
    lx.eval('select.typeFrom item')
    ask('after a mesh edit, as the kit asks', TRACK | OFF | FORCE | DISPLACE, 1)
    ask('after a mesh edit, not displaced', TRACK | OFF | FORCE, 1)
except Exception:
    result['error'] = traceback.format_exc()
(out / 'timing.json').write_text(json.dumps(result, indent=1))
lx.eval('!app.quit')
