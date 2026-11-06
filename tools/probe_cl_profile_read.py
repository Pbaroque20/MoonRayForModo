# python
"""Command line: where the time of reading a scene goes. Opens MOONRAY_PROBE_SCENE, reads it as the preview does
(host.snapshot) twice under cProfile, and writes the slowest calls of each, the meshes' sizes and the scene's item
counts to test-results/profile-read/ (report.json, first.txt, again.txt)."""
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

out = pathlib.Path(r'C:\Users\Raphael Tobar\MoonRayForModo\test-results\profile-read')
out.mkdir(parents=True, exist_ok=True)
result = {}
try:
    lx.eval('scene.open {%s} normal' % os.environ['MOONRAY_PROBE_SCENE'])
    scene = modo.Scene()
    kinds = {}
    for item in scene.iterItems():
        kinds[item.type] = kinds.get(item.type, 0) + 1
    result['items'] = dict(sorted(kinds.items(), key=lambda kv: -kv[1])[:40])
    from moonray_modo import host
    for label in ('first', 'again'):
        profile = cProfile.Profile()
        began = time.perf_counter()
        profile.enable()
        shot = host.snapshot()
        profile.disable()
        result[label + '_seconds'] = round(time.perf_counter() - began, 3)
        text = io.StringIO()
        stats = pstats.Stats(profile, stream=text).sort_stats('cumulative')
        stats.print_stats(70)
        text.write('\n---- by own time ----\n')
        stats.sort_stats('tottime').print_stats(40)
        (out / (label + '.txt')).write_text(text.getvalue(), encoding='utf-8')
    meshes = shot.get('meshes') or []
    result['meshes'] = len(meshes)
    result['faces'] = sum(len(m.get('faces') or []) for m in meshes)
    result['instances'] = sum(len(m.get('instances') or []) for m in meshes)
    result['largest'] = sorted(((len(m.get('faces') or []), m.get('name'), bool(m.get('subdivision'))) for m in meshes), reverse=True)[:12]
    result['materials'] = len(shot.get('materials') or {})
    result['extra'] = len(shot.get('extra_geometry') or [])
    result['warnings'] = (shot.get('warnings') or [])[:20]
except Exception:
    result['error'] = traceback.format_exc()
(out / 'report.json').write_text(json.dumps(result, indent=1, default=str), encoding='utf-8')
