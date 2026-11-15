# python
"""Command line: a scene with an Ocean Plane (PROBE_SCENE) read as MoonLightIPR's playblast reads it, frame after frame
(PROBE_FIRST to PROBE_LAST): animation.capture_frame under host.by_engine('moonlightipr'), then packed for MoonLightIPR
(moonlightipr_scene.pack, full-size textures). For each frame, how long the reading and the packing take, the plane's
mesh (faces, its centre, its key), its sea's tile files and whether they exist, and the packer's notices. Writes
PROBE_OUT/report.json (test-results/ocean-frames-probe)."""
import json
import os
import pathlib
import time
import traceback
import lx

out = pathlib.Path(os.environ.get('PROBE_OUT', r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\ocean-frames-probe'))
out.mkdir(parents=True, exist_ok=True)
result = {'scene': os.environ.get('PROBE_SCENE'), 'frames': {}}


def save():
    (out / 'report.json').write_text(json.dumps(result, indent=1, default=str))


try:
    lx.eval('!scene.open {%s} normal' % os.environ['PROBE_SCENE'])
    import modo
    from moonray_modo import animation, host, moonlightipr_scene, native, nodes, ocean
    fps = float(modo.Scene().fps)
    result['fps'] = fps
    first, last = int(os.environ.get('PROBE_FIRST', 9)), int(os.environ.get('PROBE_LAST', 15))
    for frame in range(first, last + 1):
        row = {}
        try:
            began = time.perf_counter()
            with host.by_engine('moonlightipr'):
                snap = animation.capture_frame(frame / fps, True, False, fps, preview=True)
            row['read_s'] = round(time.perf_counter() - began, 2)
            snap['frame'], snap['fps'], snap['_full_textures'], snap['_flat_out'] = frame, fps, True, True
            row['time'] = snap.get('time')
            planes = [m for m in snap.get('meshes') or [] if m.get('_ocean_plane')]
            row['planes'] = [{'faces': len(m['faces']), 'centre': [round(c, 2) for c in m['vertices'][0]], 'material': m['material']}
                             for m in planes]
            for m in planes:
                graph = (snap['materials'].get(m['material']) or {}).get('node_graph')
                if graph:
                    with ocean.writing(frame / fps, native.default_runtime()):
                        expanded = nodes.expand_ocean(nodes.effective(graph))
                    tiles = [n['parameters']['texture'] for k, n in expanded['nodes'].items() if k.startswith('sea__cascade') and n.get('type') == 'ImageMap']
                    row['tiles'] = [[pathlib.Path(t).name, pathlib.Path(t).is_file()] for t in tiles]
            began = time.perf_counter()
            payload, keys, warnings = moonlightipr_scene.pack(snap, 640, 360, 0.15, (), 16, False, None)
            row['pack_s'] = round(time.perf_counter() - began, 2)
            row['bytes'] = len(payload)
            row['warnings'] = warnings[:8]
        except Exception:
            row['error'] = traceback.format_exc()[-2000:]
        result['frames'][frame] = row
        save()
except Exception:
    result['error'] = traceback.format_exc()
save()
lx.eval('!app.quit')
